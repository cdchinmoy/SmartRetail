import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.core.db import db_session, context
from app.auth.dependencies import current_user
from app.tenancy.dependencies import require
from app.tenancy.repository import BranchRepository
from app.models import Tenant, Membership, Role, User, Branch, Warehouse, Audit
from app.billing.service import create_trial, require_capacity

router = APIRouter(tags=['Tenant foundation'])
class Named(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
class BranchOut(Named):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
class MemberInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    role: str = Field(pattern='^(manager|cashier)$')
class WarehouseInput(Named):
    branch_id: uuid.UUID

def audit(db, ctx, action, target):
    db.add(Audit(tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action=action, target_id=target))

@router.get('/tenants')
def tenants(user=Depends(current_user), db: Session = Depends(db_session)):
    rows = db.execute(select(Tenant, Role.name).join(Membership, Membership.tenant_id == Tenant.id).join(Role, Role.id == Membership.role_id).where(Membership.user_id == user.id, Membership.active.is_(True)).order_by(Tenant.name)).all()
    return [{'id': t.id, 'name': t.name, 'status': t.status, 'role': role} for t, role in rows]

@router.post('/tenants', status_code=201)
def create_tenant(body: Named, idempotency_key: uuid.UUID = Header(), user=Depends(current_user), db: Session = Depends(db_session)):
    # Serialize retries by actor/key before looking up the result.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': f'{user.id}:{idempotency_key}'})
    tenant = db.scalar(select(Tenant).where(Tenant.owner_id == user.id, Tenant.creation_key == idempotency_key))
    if tenant:
        if tenant.name != body.name:
            raise HTTPException(409, 'Idempotency key reused with different request')
        return {'id': tenant.id, 'name': tenant.name, 'status': tenant.status}
    tenant = Tenant(name=body.name, owner_id=user.id, creation_key=idempotency_key)
    db.add(tenant); db.flush()
    context(db, 'app.tenant_id', tenant.id)
    create_trial(db, tenant.id)
    role = db.scalar(select(Role).where(Role.name == 'owner'))
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    db.add(Branch(tenant_id=tenant.id, name='Main branch'))
    db.add(Audit(tenant_id=tenant.id, actor_id=user.id, action='tenant.created', target_id=tenant.id))
    return {'id': tenant.id, 'name': tenant.name, 'status': tenant.status}

@router.get('/branches', response_model=list[BranchOut])
def branches(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), ctx=Depends(require('branches.read')), db: Session = Depends(db_session)):
    return BranchRepository(db, ctx.tenant_id).list(offset, limit)

@router.post('/branches', response_model=BranchOut, status_code=201)
def create_branch(body: Named, ctx=Depends(require('branches.write')), db: Session = Depends(db_session)):
    require_capacity(db, ctx.tenant_id, resource='branches')
    branch = BranchRepository(db, ctx.tenant_id).create(body.name)
    audit(db, ctx, 'branch.created', branch.id)
    return branch

@router.get('/branches/{branch_id}', response_model=BranchOut)
def get_branch(branch_id: uuid.UUID, ctx=Depends(require('branches.read')), db: Session = Depends(db_session)):
    branch = BranchRepository(db, ctx.tenant_id).get(branch_id)
    if not branch:
        raise HTTPException(404, 'Branch not found')
    return branch

@router.post('/warehouses', status_code=201)
def create_warehouse(body: WarehouseInput, ctx=Depends(require('branches.write')), db: Session = Depends(db_session)):
    if not BranchRepository(db, ctx.tenant_id).get(body.branch_id):
        raise HTTPException(404, 'Branch not found')
    require_capacity(db, ctx.tenant_id, feature='warehouses')
    w = Warehouse(tenant_id=ctx.tenant_id, branch_id=body.branch_id, name=body.name)
    db.add(w); db.flush(); audit(db, ctx, 'warehouse.created', w.id)
    return {'id': w.id, 'name': w.name, 'branch_id': w.branch_id}

@router.get('/members')
def members(ctx=Depends(require('members.manage')), db: Session = Depends(db_session)):
    rows = db.execute(select(Membership, User.email, Role.name).join(User, User.id == Membership.user_id).join(Role, Role.id == Membership.role_id).where(Membership.tenant_id == ctx.tenant_id).order_by(User.email)).all()
    return [{'id': m.id, 'email': email, 'role': role, 'active': m.active} for m,email,role in rows]

@router.post('/members', status_code=201)
def add_member(body: MemberInput, ctx=Depends(require('members.manage')), db: Session = Depends(db_session)):
    require_capacity(db, ctx.tenant_id, resource='users')
    user = db.scalar(select(User).where(User.email == str(body.email).lower(), User.active.is_(True)))
    if not user:
        raise HTTPException(404, 'Registered account not found')
    role = db.scalar(select(Role).where(Role.name == body.role))
    m = Membership(tenant_id=ctx.tenant_id, user_id=user.id, role_id=role.id)
    db.add(m); db.flush(); audit(db, ctx, 'membership.created', m.id)
    return {'id': m.id}

@router.delete('/members/{member_id}', status_code=204)
def revoke_member(member_id: uuid.UUID, ctx=Depends(require('members.manage')), db: Session = Depends(db_session)):
    m = db.scalar(select(Membership).where(Membership.id == member_id, Membership.tenant_id == ctx.tenant_id).with_for_update())
    if not m:
        raise HTTPException(404, 'Membership not found')
    if db.get(Role, m.role_id).name == 'owner':
        raise HTTPException(409, 'Ownership transfer required')
    m.active = False; audit(db, ctx, 'membership.revoked', m.id)

@router.get('/audit')
def audit_list(limit: int = Query(50, ge=1, le=100), ctx=Depends(require('audit.read')), db: Session = Depends(db_session)):
    return db.scalars(select(Audit).where(Audit.tenant_id == ctx.tenant_id).order_by(Audit.created_at.desc(), Audit.id).limit(limit)).all()
