import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Literal
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.db import db_session
from app.auth.dependencies import current_user
from app.models import Tenant, PlatformAudit

router = APIRouter(prefix='/platform', tags=['Platform administration'])

def platform_admin(user=Depends(current_user)):
    if not user.platform_admin:
        raise HTTPException(403, 'Platform administrator required')
    return user
class Status(BaseModel):
    status: Literal['active','suspended']

@router.get('/overview')
def overview(user=Depends(platform_admin), db: Session = Depends(db_session)):
    return dict(db.execute(select(Tenant.status, func.count()).group_by(Tenant.status)).all())

@router.get('/tenants')
def tenants(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), user=Depends(platform_admin), db: Session = Depends(db_session)):
    return [{'id':t.id, 'name':t.name, 'status':t.status} for t in db.scalars(select(Tenant).order_by(Tenant.id).offset(offset).limit(limit))]

@router.patch('/tenants/{tenant_id}')
def status(tenant_id: uuid.UUID, body: Status, user=Depends(platform_admin), db: Session = Depends(db_session)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, 'Tenant not found')
    tenant.status = body.status
    db.add(PlatformAudit(actor_id=user.id, action=f'tenant.{body.status}', target_id=tenant.id))
    return {'id': tenant.id, 'status': tenant.status}
