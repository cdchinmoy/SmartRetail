import uuid
from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.dependencies import current_user
from app.core.db import db_session, context
from app.models import Membership, Tenant, RolePermission, Permission

@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID

def tenant_context(x_tenant_id: uuid.UUID = Header(), user=Depends(current_user), db: Session = Depends(db_session)):
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == x_tenant_id, Membership.active.is_(True)))
    if not membership:
        raise HTTPException(403, 'Business access denied')
    tenant = db.get(Tenant, x_tenant_id)
    if tenant.status != 'active':
        raise HTTPException(403, 'Business is suspended')
    context(db, 'app.tenant_id', tenant.id)
    return TenantContext(tenant.id, user.id, membership.role_id)

def require(code):
    def dependency(ctx=Depends(tenant_context), db: Session = Depends(db_session)):
        allowed = db.scalar(select(Permission.id).join(RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id == ctx.role_id, Permission.code == code))
        if not allowed:
            raise HTTPException(403, 'Permission denied')
        return ctx
    return dependency
