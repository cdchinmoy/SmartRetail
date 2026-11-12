import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from sqlalchemy import select,func,text
from test_integration import client, account, tenant
from app.billing.models import Subscription, BillingInvoice, BillingOperation, ProviderLink, ProviderEvent, BillingNotice
from app.billing.service import now, tick
from app.billing.worker import process_tenant
from app.billing.providers import ProviderError
from app.core.db import SessionLocal, context
from app.core.config import settings

pytestmark=pytest.mark.skipif(os.getenv('RUN_DB_TESTS')!='1',reason='Requires migrated PostgreSQL')

def queue(client,headers,path,body=None,key=None):
    response=client.post('/api/v1'+path,headers={**headers,'Idempotency-Key':key or str(uuid.uuid4())},**({'json':body} if body is not None else {}))
    assert response.status_code==202,response.text
    process_tenant(uuid.UUID(headers['X-Tenant-ID']))
    return response.json()

def paid_tenant(client,plan='growth'):
    _,h=account(client);h=tenant(client,h)
    queue(client,h,'/billing/checkout',{'plan':plan,'cycle':'monthly'})
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='trialing'
    queue(client,h,'/billing/sandbox/charge')
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='active'
    return h

def test_trial_and_paid_upgrade_and_idempotent_checkout(client):
    _,h=account(client);h=tenant(client,h)
    before=client.get('/api/v1/subscriptions/current',headers=h).json()
    assert before['status']=='trialing' and before['entitlements']['limits']['branches']==1
    assert client.post('/api/v1/branches',headers=h,json={'name':'Over quota'}).status_code==409
    key=str(uuid.uuid4());body={'plan':'growth','cycle':'monthly'}
    original=queue(client,h,'/billing/checkout',body,key)
    repeated=client.post('/api/v1/billing/checkout',headers={**h,'Idempotency-Key':key},json=body)
    assert repeated.status_code==202 and repeated.json()['id']==original['id']
    changed=client.post('/api/v1/billing/checkout',headers={**h,'Idempotency-Key':key},json={'plan':'business','cycle':'monthly'})
    assert changed.status_code==409
    queue(client,h,'/billing/sandbox/charge')
    assert client.post('/api/v1/branches',headers=h,json={'name':'Second'}).status_code==201
    invoices=client.get('/api/v1/billing/invoices',headers=h).json()
    assert len(invoices)==1 and invoices[0]['amount']==149900
    queue(client,h,'/billing/reconcile')
    assert len(client.get('/api/v1/billing/invoices',headers=h).json())==1

def test_signed_duplicate_webhooks_and_replay(client,monkeypatch):
    h=paid_tenant(client);monkeypatch.setattr(settings,'sandbox_webhook_secret','integration-webhook-secret')
    sub=client.get('/api/v1/subscriptions/current',headers=h).json()
    event={'created_at':int(time.time()),'event':'subscription.charged','payload':{'subscription':{'entity':{'id':sub['provider_ref']}}}}
    body=json.dumps(event).encode();sig=hmac.new(b'integration-webhook-secret',body,hashlib.sha256).hexdigest()
    headers={'X-Billing-Signature':sig,'X-Billing-Event-ID':str(uuid.uuid4())}
    assert client.post('/api/v1/billing/webhooks/sandbox',content=body,headers={**headers,'X-Billing-Signature':'bad'}).status_code==401
    r=client.post('/api/v1/billing/webhooks/sandbox',content=body,headers=headers);assert r.status_code==200,r.text
    assert client.post('/api/v1/billing/webhooks/sandbox',content=body,headers=headers).json()['duplicate']
    assert client.post('/api/v1/billing/webhooks/sandbox',content=body,headers={**headers,'X-Billing-Event-ID':str(uuid.uuid4())}).json()['duplicate']
    process_tenant(uuid.UUID(h['X-Tenant-ID']))
    assert len(client.get('/api/v1/billing/invoices',headers=h).json())==1
    event['created_at']=int(time.time())-8*86400
    body=json.dumps(event).encode();headers['X-Billing-Signature']=hmac.new(b'integration-webhook-secret',body,hashlib.sha256).hexdigest()
    assert client.post('/api/v1/billing/webhooks/sandbox',content=body,headers=headers).status_code==400

def test_expired_trial_keeps_reads_but_blocks_writes(client):
    _,h=account(client);h=tenant(client,h)
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID'])
        sub=db.scalar(select(Subscription));sub.trial_ends_at=now()-timedelta(seconds=1)
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='expired'
    assert client.get('/api/v1/branches',headers=h).status_code==200
    assert client.post('/api/v1/branches',headers=h,json={'name':'Denied'}).status_code==402
    queue(client,h,'/billing/checkout',{'plan':'starter','cycle':'yearly'})

def test_billing_tenant_isolation_and_cashier_denial(client):
    a=paid_tenant(client);_,b=account(client);b=tenant(client,b)
    invoice=client.get('/api/v1/billing/invoices',headers=a).json()[0]
    assert client.get('/api/v1/billing/invoices/'+invoice['id'],headers=b).status_code==404
    assert client.get('/api/v1/subscriptions/current',headers={**b,'X-Tenant-ID':a['X-Tenant-ID']}).status_code==403
    email,cashier=account(client)
    assert client.post('/api/v1/members',headers=a,json={'email':email,'role':'cashier'}).status_code==201
    cashier={**cashier,'X-Tenant-ID':a['X-Tenant-ID']}
    assert client.get('/api/v1/subscriptions/current',headers=cashier).status_code==403
    with SessionLocal.begin() as db:
        assert db.scalar(select(func.count()).select_from(BillingInvoice))==0
        context(db,'app.tenant_id',b['X-Tenant-ID'])
        assert db.scalar(select(func.count()).select_from(BillingInvoice))==0

def test_concurrent_branch_quota(client):
    h=paid_tenant(client)
    assert client.post('/api/v1/branches',headers=h,json={'name':'Second'}).status_code==201
    def add(i):return client.post('/api/v1/branches',headers=h,json={'name':'Concurrent '+str(i)}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(add,[1,2]))
    assert sorted(results)==[201,409]

def test_scheduled_downgrade_retains_excess_records(client):
    h=paid_tenant(client)
    assert client.post('/api/v1/branches',headers=h,json={'name':'Keep this'}).status_code==201
    queue(client,h,'/subscriptions/change',{'plan':'starter','cycle':'monthly'})
    before=client.get('/api/v1/subscriptions/current',headers=h).json()
    assert before['plan_code']=='growth' and before['pending_plan_code']=='starter'
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID'])
        sub=db.scalar(select(Subscription));sub.period_end=now()-timedelta(seconds=1)
        link=db.scalar(select(ProviderLink).where(ProviderLink.provider_ref==sub.provider_ref))
        state=dict(link.sandbox_state);state['current_end']=int(sub.period_end.timestamp());link.sandbox_state=state
    queue(client,h,'/billing/sandbox/charge')
    after=client.get('/api/v1/subscriptions/current',headers=h).json()
    assert after['plan_code']=='starter' and 'branches' in after['entitlements']['over_limit']
    assert len(client.get('/api/v1/branches',headers=h).json())==2
    assert client.post('/api/v1/branches',headers=h,json={'name':'Blocked'}).status_code==409

def test_cancellation_retains_paid_access_then_expires(client):
    h=paid_tenant(client);queue(client,h,'/subscriptions/cancel')
    current=client.get('/api/v1/subscriptions/current',headers=h).json()
    assert current['status']=='active' and current['cancel_at_period_end']
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);sub=db.scalar(select(Subscription));sub.period_end=now()-timedelta(seconds=1)
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='canceled'

def test_grace_period_and_suspension(client):
    h=paid_tenant(client)
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);sub=db.scalar(select(Subscription))
        sub.period_end=now()-timedelta(hours=1)
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='grace_period'
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);sub=db.scalar(select(Subscription));sub.grace_ends_at=now()-timedelta(seconds=1)
    assert client.get('/api/v1/subscriptions/current',headers=h).json()['status']=='suspended'
    assert client.post('/api/v1/branches',headers=h,json={'name':'Blocked'}).status_code==402

def test_uncertain_provider_mutation_is_not_retried(client,monkeypatch):
    from app.billing import worker
    _,h=account(client);h=tenant(client,h)
    r=client.post('/api/v1/billing/checkout',headers={**h,'Idempotency-Key':str(uuid.uuid4())},json={'plan':'growth','cycle':'monthly'})
    assert r.status_code==202
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);op=db.get(BillingOperation,r.json()['id']);op.payload={**op.payload,'provider':'razorpay'}
    class Ambiguous:
        def execute(self,*args):raise ProviderError('Unknown provider outcome',uncertain=True)
    monkeypatch.setattr(worker,'provider_for',lambda name:Ambiguous())
    process_tenant(uuid.UUID(h['X-Tenant-ID']));process_tenant(uuid.UUID(h['X-Tenant-ID']))
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);op=db.get(BillingOperation,r.json()['id'])
        assert op.status=='uncertain' and op.attempts==1

def test_trial_warning_is_deduplicated(client):
    _,h=account(client);h=tenant(client,h)
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);sub=db.scalar(select(Subscription));sub.trial_ends_at=now()+timedelta(days=2)
        tick(db,sub);tick(db,sub)
        assert db.scalar(select(func.count()).select_from(BillingNotice).where(BillingNotice.key=='trial.ending'))==1


def test_sandbox_entitlements_do_not_transfer_to_production(client,monkeypatch):
    h=paid_tenant(client)
    monkeypatch.setattr(settings,'environment','production')
    result=client.get('/api/v1/subscriptions/current',headers=h)
    assert result.status_code==200
    assert result.json()['entitlements']['can_write'] is False
    assert client.post('/api/v1/branches',headers=h,json={'name':'Forbidden production use'}).status_code==402


def test_provider_active_without_captured_invoice_cannot_grant_access(client):
    from app.billing.service import apply_snapshot
    _,h=account(client);h=tenant(client,h)
    queue(client,h,'/billing/checkout',{'plan':'business','cycle':'monthly'})
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);sub=db.scalar(select(Subscription))
        sub.status='expired';sub.trial_ends_at=now()-timedelta(seconds=1)
        apply_snapshot(db,sub,{'id':sub.provider_ref,'plan_ref':'sandbox:business:monthly','status':'active','current_start':int(time.time()),'current_end':int(time.time())+86400,'invoices':[]},'sandbox')
        assert sub.status=='expired' and sub.plan_code=='starter'


def test_billing_does_not_reactivate_administratively_suspended_business(client):
    from app.models import Tenant
    h=paid_tenant(client)
    with SessionLocal.begin() as db:
        business=db.get(Tenant,h['X-Tenant-ID']);business.status='suspended'
    process_tenant(uuid.UUID(h['X-Tenant-ID']))
    assert client.get('/api/v1/branches',headers=h).status_code==403
    with SessionLocal() as db:assert db.get(Tenant,h['X-Tenant-ID']).status=='suspended'


def test_interrupted_external_mutation_requires_operator_review(client):
    _,h=account(client);h=tenant(client,h)
    response=client.post('/api/v1/billing/checkout',headers={**h,'Idempotency-Key':str(uuid.uuid4())},json={'plan':'growth','cycle':'monthly'})
    assert response.status_code==202
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);op=db.get(BillingOperation,response.json()['id'])
        op.status='running';op.updated_at=now()-timedelta(minutes=11);op.payload={**op.payload,'provider':'razorpay'}
    process_tenant(uuid.UUID(h['X-Tenant-ID']))
    with SessionLocal() as db:
        context(db,'app.tenant_id',h['X-Tenant-ID']);op=db.get(BillingOperation,response.json()['id'])
        assert op.status=='uncertain'
