"""Requires migrated disposable PostgreSQL. No SQLite substitute for RLS."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Set RUN_DB_TESTS=1 with a migrated disposable PostgreSQL database')

@pytest.fixture
def client():
    from app.main import app
    from app.auth.router import rate_limit
    # Rate limiter itself is tested separately. Redis is not needed for DB tests.
    app.dependency_overrides[rate_limit] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def account(client):
    email = f'{uuid.uuid4()}@example.com'
    r=client.post('/api/v1/auth/register',json={'email':email,'password':'Test-password-12345'})
    assert r.status_code == 201,r.text
    return email, {'Authorization':'Bearer '+r.json()['access_token']}

def tenant(client, headers):
    r=client.post('/api/v1/tenants',headers={**headers,'Idempotency-Key':str(uuid.uuid4())},json={'name':'Test shop'})
    assert r.status_code == 201,r.text
    return {**headers,'X-Tenant-ID':r.json()['id']}

def test_cross_tenant_reads_writes_and_context_reset(client):
    from app.core.db import SessionLocal, context
    _, a=account(client); a=tenant(client,a)
    _, b=account(client); b=tenant(client,b)
    bid=client.get('/api/v1/branches',headers=b).json()[0]['id']
    assert client.get('/api/v1/branches/'+bid,headers=a).status_code == 404
    assert client.get('/api/v1/branches',headers={**a,'X-Tenant-ID':b['X-Tenant-ID']}).status_code == 403
    assert client.post('/api/v1/warehouses',headers=a,json={'name':'Invalid','branch_id':bid}).status_code == 404
    with SessionLocal.begin() as db:
        assert db.execute(text('SELECT count(*) FROM branches')).scalar() == 0
        context(db,'app.tenant_id',a['X-Tenant-ID'])
        ids=db.execute(text('SELECT tenant_id FROM branches')).scalars().all()
        assert ids and all(str(i)==a['X-Tenant-ID'] for i in ids)
    with SessionLocal.begin() as db:
        assert db.execute(text('SELECT count(*) FROM branches')).scalar() == 0
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:
            context(db,'app.tenant_id',a['X-Tenant-ID'])
            db.execute(text('INSERT INTO branches(id,tenant_id,name) VALUES(:id,:tenant,:name)'),{'id':uuid.uuid4(),'tenant':b['X-Tenant-ID'],'name':'Forbidden'})

def test_membership_rbac_and_revocation(client):
    _, owner=account(client); owner=tenant(client,owner)
    email, cashier=account(client)
    r=client.post('/api/v1/members',headers=owner,json={'email':email,'role':'cashier'})
    assert r.status_code==201,r.text
    cashier={**cashier,'X-Tenant-ID':owner['X-Tenant-ID']}
    assert client.get('/api/v1/branches',headers=cashier).status_code==200
    assert client.post('/api/v1/branches',headers=cashier,json={'name':'Forbidden'}).status_code==403
    assert client.delete('/api/v1/members/'+r.json()['id'],headers=owner).status_code==204
    assert client.get('/api/v1/branches',headers=cashier).status_code==403

def test_idempotent_onboarding(client):
    _, headers=account(client)
    headers={**headers,'Idempotency-Key':str(uuid.uuid4())}
    def create(_):
        return client.post('/api/v1/tenants',headers=headers,json={'name':'Concurrent shop'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(create,range(2)))
    assert all(r.status_code==201 for r in results)
    assert results[0].json()['id']==results[1].json()['id']
    assert client.post('/api/v1/tenants',headers=headers,json={'name':'Changed'}).status_code==409

def test_refresh_reuse_revokes_family(client):
    from app.core.config import settings
    _, headers=account(client)
    old=client.cookies.get('refresh')
    origin={'Origin':settings.web_origin}
    r=client.post('/api/v1/auth/refresh',headers=origin)
    assert r.status_code==200,r.text
    access=r.json()['access_token']
    client.cookies.clear(); client.cookies.set('refresh',old,path='/api/v1/auth')
    assert client.post('/api/v1/auth/refresh',headers=origin).status_code==401
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+access}).status_code==401

def test_platform_role_not_tenant_access(client):
    from app.core.db import SessionLocal
    email, admin=account(client)
    # Administrative setup only, not an exposed API.
    with SessionLocal.begin() as db:
        db.execute(text('UPDATE users SET platform_admin=true WHERE email=:e'),{'e':email})
    _, owner=account(client); owner=tenant(client,owner)
    assert client.get('/api/v1/platform/tenants',headers=admin).status_code==200
    assert client.get('/api/v1/branches',headers={**admin,'X-Tenant-ID':owner['X-Tenant-ID']}).status_code==403
    assert client.patch('/api/v1/platform/tenants/'+owner['X-Tenant-ID'],headers=admin,json={'status':'suspended'}).status_code==200
    assert client.get('/api/v1/branches',headers=owner).status_code==403
    assert client.get('/api/v1/platform/tenants',headers=owner).status_code==403
