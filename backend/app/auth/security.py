import uuid
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from app.core.config import settings

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash('non-user-dummy-password')

def verify(password, hashed):
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False

def token(user_id, kind, jti, minutes):
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': str(user_id), 'type': kind, 'jti': str(jti), 'iat': now,
                       'exp': now + timedelta(minutes=minutes), 'iss': 'smartretail', 'aud': 'smartretail-api'}, settings.jwt_secret, algorithm='HS256')

def decode(raw, kind):
    try:
        data = jwt.decode(raw, settings.jwt_secret, algorithms=['HS256'], issuer='smartretail', audience='smartretail-api', options={'require': ['exp','iat','sub','jti','type']})
        if data['type'] != kind:
            raise ValueError()
        uuid.UUID(data['sub']); uuid.UUID(data['jti'])
        return data
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, 'Invalid or expired token')
