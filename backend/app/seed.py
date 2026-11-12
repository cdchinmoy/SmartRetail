"""Development-only seed; requires explicit passwords, never runs automatically."""
import os
import uuid
from sqlalchemy import select
from app.core.db import SessionLocal, context
from app.models import User, Tenant, Membership, Role, Branch
from app.auth.security import hasher
from app.billing.service import create_trial

def main():
    password = os.environ['DEMO_PASSWORD']
    if len(password) < 12:
        raise ValueError('DEMO_PASSWORD must be at least 12 characters')
    with SessionLocal.begin() as db:
        for i, name in enumerate(['Lotus Retail', 'Harbor Market'], 1):
            email = f'owner{i}@example.com'
            user = db.scalar(select(User).where(User.email == email))
            if user:
                continue
            user = User(email=email, password_hash=hasher.hash(password))
            db.add(user); db.flush()
            context(db, 'app.user_id', user.id)
            tenant = Tenant(name=name, owner_id=user.id, creation_key=uuid.uuid4())
            db.add(tenant); db.flush(); context(db, 'app.tenant_id', tenant.id)
            create_trial(db, tenant.id)
            role = db.scalar(select(Role).where(Role.name == 'owner'))
            db.add(Membership(tenant_id=tenant.id,user_id=user.id,role_id=role.id))
            db.add(Branch(tenant_id=tenant.id,name=f'{name} headquarters'))
            # Flush before switching transaction-local context to the second tenant.
            db.flush()
        email = 'platform@example.com'
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(email=email, password_hash=hasher.hash(password), platform_admin=True))
    print('Development accounts ready: owner1@example.com, owner2@example.com, platform@example.com')
if __name__ == '__main__':
    main()
