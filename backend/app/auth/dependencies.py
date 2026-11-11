from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.db import db_session, context
from app.models import User, RefreshSession
from app.auth.security import decode

bearer = HTTPBearer(auto_error=False)

def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(db_session)):
    if not credentials:
        raise HTTPException(401, 'Authentication required')
    claims = decode(credentials.credentials, 'access')
    user = db.get(User, claims['sub'])
    session = db.get(RefreshSession, claims['jti'])
    if not user or not user.active or not session or session.revoked or session.user_id != user.id:
        raise HTTPException(401, 'Session revoked')
    context(db, 'app.user_id', user.id)
    return user
