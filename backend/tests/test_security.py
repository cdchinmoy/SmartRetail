import os
import uuid
from datetime import datetime, timedelta, timezone
os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://smartretail_app:unused@localhost/smartretail')
os.environ.setdefault('JWT_SECRET', 'unit-test-only-secret-with-at-least-32-characters')
import jwt
import pytest
from fastapi import HTTPException
from app.auth.security import token, decode, verify, hasher
from app.core.config import settings

def test_password_hash_is_salted_and_verifiable():
    first, second = hasher.hash('A secure password'), hasher.hash('A secure password')
    assert first != second
    assert verify('A secure password', first)
    assert not verify('wrong', first)

@pytest.mark.parametrize('kind', ['access','refresh'])
def test_token_round_trip(kind):
    uid, jti = uuid.uuid4(), uuid.uuid4()
    claims = decode(token(uid,kind,jti,15),kind)
    assert claims['sub'] == str(uid) and claims['jti'] == str(jti)

def test_refresh_not_usable_as_access():
    with pytest.raises(HTTPException):
        decode(token(uuid.uuid4(),'refresh',uuid.uuid4(),15),'access')

def test_expired_token():
    with pytest.raises(HTTPException):
        decode(token(uuid.uuid4(),'access',uuid.uuid4(),-1),'access')

@pytest.mark.parametrize('raw', ['', 'bad.jwt.value', 'eyJhbGciOiJub25lIn0.e30.'])
def test_invalid_tokens(raw):
    with pytest.raises(HTTPException):
        decode(raw, 'access')

def test_wrong_signing_key():
    raw = jwt.encode({'sub':str(uuid.uuid4()),'jti':str(uuid.uuid4()),'type':'access','iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(minutes=1),'iss':'smartretail','aud':'smartretail-api'},'attacker-key-that-is-at-least-32-characters',algorithm='HS256')
    with pytest.raises(HTTPException):
        decode(raw,'access')

def test_extra_tenant_id_rejected_in_branch_body():
    from app.tenancy.router import Named
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Named(name='test',tenant_id=str(uuid.uuid4()))

def test_rate_limit_and_unavailability(monkeypatch):
    from app.auth.router import rate_limit, redis
    from starlette.requests import Request
    from redis.exceptions import ConnectionError
    request=Request({'type':'http','client':('127.0.0.1',1234),'headers':[]})
    monkeypatch.setattr(redis,'eval',lambda *args:31)
    with pytest.raises(HTTPException) as exc: rate_limit(request)
    assert exc.value.status_code == 429
    def failed(*args): raise ConnectionError()
    monkeypatch.setattr(redis,'eval',failed)
    with pytest.raises(HTTPException) as exc: rate_limit(request)
    assert exc.value.status_code == 503

def test_cookie_origin_guard():
    from app.auth.router import check_origin
    from starlette.requests import Request
    with pytest.raises(HTTPException):
        check_origin(Request({'type':'http','headers':[(b'origin',b'https://attacker.example')]}))
    check_origin(Request({'type':'http','headers':[(b'origin',settings.web_origin.encode())]}))
