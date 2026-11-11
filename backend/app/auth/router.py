import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update, text
from sqlalchemy.orm import Session
from redis import Redis
from redis.exceptions import RedisError
from app.core.config import settings
from app.core.db import db_session
from app.models import User, RefreshSession
from app.auth.security import hasher, verify, DUMMY_HASH, token, decode
from app.auth.dependencies import current_user

router = APIRouter(prefix='/auth', tags=['Authentication'])
redis = Redis.from_url(settings.redis_url)
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

def rate_limit(request: Request):
    # Direct socket address only. Configure a trusted proxy before using forwarded IPs.
    key = f'auth-rate:{request.client.host}'
    try:
        n = redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", 1, key)
    except RedisError:
        raise HTTPException(503, 'Authentication temporarily unavailable')
    if n > 30:
        raise HTTPException(429, 'Too many authentication requests')

def check_origin(request: Request):
    if request.headers.get('origin') != settings.web_origin:
        raise HTTPException(403, 'Trusted Origin required')

def issue(db, user, response, family=None):
    session = RefreshSession(user_id=user.id, family_id=family or uuid.uuid4(), expires_at=datetime.now(timezone.utc)+timedelta(days=7))
    db.add(session); db.flush()
    response.set_cookie('refresh', token(user.id, 'refresh', session.id, 7*24*60), httponly=True, secure=settings.secure_cookies, samesite='strict', path='/api/v1/auth', max_age=7*24*3600)
    response.headers['Cache-Control'] = 'no-store'
    return {'access_token': token(user.id, 'access', session.id, 15), 'token_type': 'bearer'}

@router.post('/register', status_code=201, dependencies=[Depends(rate_limit)])
def register(body: Credentials, response: Response, db: Session = Depends(db_session)):
    email = str(body.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'Account cannot be created')
    user = User(email=email, password_hash=hasher.hash(body.password))
    db.add(user); db.flush()
    return issue(db, user, response)

@router.post('/login', dependencies=[Depends(rate_limit)])
def login(body: Credentials, response: Response, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    good = verify(body.password, user.password_hash if user else DUMMY_HASH)
    if not good or not user or not user.active:
        raise HTTPException(401, 'Invalid credentials')
    return issue(db, user, response)

@router.post('/refresh', dependencies=[Depends(rate_limit), Depends(check_origin)])
def refresh(request: Request, response: Response, db: Session = Depends(db_session)):
    claims = decode(request.cookies.get('refresh', ''), 'refresh')
    # Serialize all operations for this user, including logout and replay revocation.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:uid, 0))'), {'uid': claims['sub']})
    old = db.scalar(select(RefreshSession).where(RefreshSession.id == claims['jti']).with_for_update())
    if not old or str(old.user_id) != claims['sub']:
        raise HTTPException(401, 'Invalid session')
    if old.consumed or old.revoked:
        db.execute(update(RefreshSession).where(RefreshSession.family_id == old.family_id).values(revoked=True))
        # Return an error response (do not raise and roll back the revocation).
        response.status_code = 401
        response.delete_cookie('refresh', path='/api/v1/auth')
        return {'error': {'code': 'REFRESH_REUSE', 'message': 'Refresh reuse detected; sign in again'}, 'request_id': request.state.request_id}
    user = db.get(User, old.user_id)
    if old.expires_at <= datetime.now(timezone.utc) or not user.active:
        raise HTTPException(401, 'Session expired')
    old.consumed = True
    return issue(db, user, response, old.family_id)

@router.post('/logout', dependencies=[Depends(check_origin)])
def logout(response: Response, user=Depends(current_user), db: Session = Depends(db_session)):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:uid, 0))'), {'uid': str(user.id)})
    db.execute(update(RefreshSession).where(RefreshSession.user_id == user.id).values(revoked=True))
    response.delete_cookie('refresh', path='/api/v1/auth')
    return {'detail': 'All sessions revoked'}

@router.get('/me')
def me(user=Depends(current_user)):
    return {'id': user.id, 'email': user.email, 'platform_admin': user.platform_admin}
