import hashlib
import json
import time
import uuid
from datetime import timezone
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.core.db import db_session, context
from app.core.config import settings
from app.models import Tenant, PlatformAudit
from app.tenancy.dependencies import require
from app.platform.router import platform_admin
from app.billing.models import Plan, Subscription, BillingOperation, BillingInvoice, BillingNotice, ProviderLink, ProviderEvent
from app.billing.service import subscription, entitlements, enqueue, plan_by_code, apply_snapshot, now
from app.billing.providers import valid_signature, RazorpayProvider, ProviderError

router=APIRouter(tags=['Subscriptions and billing'])

class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    plan: str = Field(min_length=1,max_length=40)
    cycle: Literal['monthly','yearly']
class Mapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    monthly_id: str = Field(pattern=r'^plan_[A-Za-z0-9]+$')
    yearly_id: str = Field(pattern=r'^plan_[A-Za-z0-9]+$')
class Recovery(BaseModel):
    provider_ref: str = Field(pattern=r'^sub_[A-Za-z0-9]+$')
class PlanInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^[a-z][a-z0-9_-]{1,39}$')
    name: str = Field(min_length=1,max_length=80)
    monthly_amount: int = Field(gt=0,le=100000000)
    yearly_amount: int = Field(gt=0,le=1000000000)
    branch_limit: int = Field(ge=1,le=100000)
    user_limit: int = Field(ge=1,le=100000)
    warehouses: bool = False


def plan_output(plan,admin=False):
    data={k:getattr(plan,k) for k in ['code','name','monthly_amount','yearly_amount','currency','branch_limit','user_limit','features','self_service','active']}
    data['checkout_ready']=plan.self_service and (settings.billing_provider=='sandbox' or bool(plan.razorpay_monthly_id and plan.razorpay_yearly_id))
    if admin: data.update(monthly_id=plan.razorpay_monthly_id,yearly_id=plan.razorpay_yearly_id)
    return data

def operation_output(operation):
    return {k:getattr(operation,k) for k in ['id','kind','status','result','error','created_at','updated_at','attempts']}

@router.get('/subscriptions/plans')
def plans(db:Session=Depends(db_session)):
    return {'provider':settings.billing_provider,'trial_days':settings.trial_days,'grace_days':settings.grace_days,'plans':[plan_output(p) for p in db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.monthly_amount))]}

@router.get('/subscriptions/current')
def current(ctx=Depends(require('billing.read')),db:Session=Depends(db_session)):
    sub=subscription(db,ctx.tenant_id)
    rights=entitlements(db,sub)
    result={k:getattr(sub,k) for k in ['id','plan_code','cycle','status','trial_ends_at','period_start','period_end','cancel_at_period_end','pending_plan_code','pending_cycle','provider','provider_ref','provider_status','synced_at','grace_ends_at']}
    result.update(entitlements=rights,provider_mode=settings.billing_provider)
    result['notices']=[{'id':n.id,'message':n.message,'created_at':n.created_at} for n in db.scalars(select(BillingNotice).where(BillingNotice.tenant_id==ctx.tenant_id).order_by(BillingNotice.created_at.desc()).limit(20))]
    return result

@router.post('/billing/checkout',status_code=202)
def checkout(body:Selection,idempotency_key:uuid.UUID=Header(),ctx=Depends(require('billing.manage')),db:Session=Depends(db_session)):
    return operation_output(enqueue(db,ctx.tenant_id,idempotency_key,'checkout',body.model_dump(),ctx.user_id))

@router.post('/subscriptions/change',status_code=202)
def change(body:Selection,idempotency_key:uuid.UUID=Header(),ctx=Depends(require('billing.manage')),db:Session=Depends(db_session)):
    return operation_output(enqueue(db,ctx.tenant_id,idempotency_key,'schedule',body.model_dump(),ctx.user_id))

@router.post('/subscriptions/cancel',status_code=202)
def cancel(idempotency_key:uuid.UUID=Header(),ctx=Depends(require('billing.manage')),db:Session=Depends(db_session)):
    return operation_output(enqueue(db,ctx.tenant_id,idempotency_key,'cancel',{},ctx.user_id))

@router.post('/billing/reconcile',status_code=202)
def reconcile(idempotency_key:uuid.UUID=Header(),ctx=Depends(require('billing.manage')),db:Session=Depends(db_session)):
    return operation_output(enqueue(db,ctx.tenant_id,idempotency_key,'reconcile',{},ctx.user_id))

@router.post('/billing/sandbox/{action}',status_code=202)
def sandbox(action:Literal['charge','fail'],idempotency_key:uuid.UUID=Header(),ctx=Depends(require('billing.manage')),db:Session=Depends(db_session)):
    return operation_output(enqueue(db,ctx.tenant_id,idempotency_key,'sandbox_'+action,{},ctx.user_id))

@router.get('/billing/operations')
def operations(limit:int=Query(20,ge=1,le=100),ctx=Depends(require('billing.read')),db:Session=Depends(db_session)):
    return [operation_output(o) for o in db.scalars(select(BillingOperation).where(BillingOperation.tenant_id==ctx.tenant_id).order_by(BillingOperation.created_at.desc()).limit(limit))]

@router.get('/billing/invoices')
def invoices(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),ctx=Depends(require('billing.read')),db:Session=Depends(db_session)):
    return db.scalars(select(BillingInvoice).where(BillingInvoice.tenant_id==ctx.tenant_id).order_by(BillingInvoice.paid_at.desc()).offset(offset).limit(limit)).all()

@router.get('/billing/invoices/{invoice_id}')
def invoice(invoice_id:uuid.UUID,ctx=Depends(require('billing.read')),db:Session=Depends(db_session)):
    row=db.scalar(select(BillingInvoice).where(BillingInvoice.id==invoice_id,BillingInvoice.tenant_id==ctx.tenant_id))
    if not row: raise HTTPException(404,'Invoice not found')
    return row

@router.post('/billing/webhooks/{provider}')
async def webhook(provider:Literal['sandbox','razorpay'],request:Request,db:Session=Depends(db_session)):
    if provider!=settings.billing_provider or (provider=='sandbox' and settings.environment!='development'):
        raise HTTPException(404,'Provider disabled')
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>262144: raise HTTPException(413,'Webhook too large')
    secrets=[settings.razorpay_webhook_secret,settings.razorpay_previous_webhook_secret] if provider=='razorpay' else [settings.sandbox_webhook_secret]
    signature=request.headers.get('x-razorpay-signature' if provider=='razorpay' else 'x-billing-signature','')
    if not valid_signature(bytes(body),signature,secrets): raise HTTPException(401,'Invalid webhook signature')
    try:
        data=json.loads(body)
        created=int(data['created_at'])
        ref=data['payload']['subscription']['entity']['id']
        event_type=data['event']
        if not isinstance(ref,str) or not isinstance(event_type,str) or len(ref)>100 or len(event_type)>80: raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise HTTPException(400,'Malformed webhook')
    if created>time.time()+300 or created<time.time()-7*86400:
        raise HTTPException(400,'Webhook outside replay window; use reconciliation')
    event_id=request.headers.get('x-razorpay-event-id' if provider=='razorpay' else 'x-billing-event-id','')
    if not event_id or len(event_id)>150: raise HTTPException(400,'Event ID required')
    digest=hashlib.sha256(body).hexdigest()
    # Header ID is not signed: also deduplicate the signed body's digest.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'webhook:'+provider})
    prior=db.scalar(select(ProviderEvent).where(ProviderEvent.provider==provider,ProviderEvent.event_id==event_id))
    if prior:
        if prior.body_hash!=digest: raise HTTPException(409,'Event ID payload mismatch')
        return {'accepted':True,'duplicate':True}
    if db.scalar(select(ProviderEvent.id).where(ProviderEvent.provider==provider,ProviderEvent.body_hash==digest)):
        return {'accepted':True,'duplicate':True}
    link=db.scalar(select(ProviderLink).where(ProviderLink.provider==provider,ProviderLink.provider_ref==ref))
    if not link: raise HTTPException(503,'Provider subscription is not linked yet; retry delivery')
    context(db,'app.tenant_id',link.tenant_id)
    db.add(ProviderEvent(provider=provider,event_id=event_id,body_hash=digest,tenant_id=link.tenant_id,provider_ref=ref,event_type=event_type))
    sub=subscription(db,link.tenant_id)
    if sub.provider_ref==ref:
        enqueue(db,link.tenant_id,uuid.uuid5(uuid.NAMESPACE_URL,provider+':event:'+digest),'reconcile',{})
    return {'accepted':True,'duplicate':False}

@router.get('/platform/billing/plans')
def admin_plans(user=Depends(platform_admin),db:Session=Depends(db_session)):
    return [plan_output(p,True) for p in db.scalars(select(Plan).order_by(Plan.monthly_amount))]

@router.post('/platform/billing/plans',status_code=201)
def create_plan(body:PlanInput,user=Depends(platform_admin),db:Session=Depends(db_session)):
    values=body.model_dump();warehouses=values.pop('warehouses')
    plan=Plan(**values,currency='INR',features={'branches':True,'team':True,'warehouses':warehouses},self_service=True,active=True)
    db.add(plan);db.flush()
    db.add(PlatformAudit(actor_id=user.id,action='billing.plan.created',target_id=plan.id))
    return plan_output(plan,True)

@router.put('/platform/billing/plans/{code}/provider')
def map_plan(code:str,body:Mapping,user=Depends(platform_admin),db:Session=Depends(db_session)):
    if body.monthly_id==body.yearly_id: raise HTTPException(422,'Monthly and yearly provider plans must differ')
    plan=plan_by_code(db,code)
    if (plan.razorpay_monthly_id and plan.razorpay_monthly_id!=body.monthly_id) or (plan.razorpay_yearly_id and plan.razorpay_yearly_id!=body.yearly_id):
        raise HTTPException(409,'Existing provider mappings are immutable; create a new catalog plan version')
    occupied=set()
    for existing in db.scalars(select(Plan).where(Plan.id!=plan.id)):
        occupied.update([existing.razorpay_monthly_id,existing.razorpay_yearly_id])
    if body.monthly_id in occupied or body.yearly_id in occupied: raise HTTPException(409,'Provider plan is already mapped')
    plan.razorpay_monthly_id=body.monthly_id;plan.razorpay_yearly_id=body.yearly_id
    db.add(PlatformAudit(actor_id=user.id,action='billing.plan.mapped',target_id=plan.id))
    return plan_output(plan,True)

@router.get('/platform/billing/overview')
def overview(user=Depends(platform_admin),db:Session=Depends(db_session)):
    counts={};mrr=Decimal(0);sandbox_active=0;attention=[]
    # Platform role sees SaaS billing metadata only, never retail rows.
    for tenant_id in db.scalars(select(Tenant.id)).all():
        context(db,'app.tenant_id',tenant_id)
        sub=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant_id))
        if not sub: continue
        status=sub.status
        if sub.period_end and sub.period_end<=now() and status=='active': status='past_due'
        if status=='trialing' and sub.trial_ends_at<=now(): status='expired'
        counts[status]=counts.get(status,0)+1
        if status=='active':
            if sub.provider=='sandbox': sandbox_active+=1
            else:
                paid=db.scalar(select(BillingInvoice).where(BillingInvoice.tenant_id==tenant_id).order_by(BillingInvoice.period_end.desc()).limit(1))
                if paid: mrr+=Decimal(paid.amount)/(12 if paid.cycle=='yearly' else 1)
        for operation in db.scalars(select(BillingOperation).where(BillingOperation.tenant_id==tenant_id,BillingOperation.status.in_(['failed','uncertain'])).order_by(BillingOperation.created_at.desc()).limit(5)):
            attention.append({'tenant_id':str(tenant_id),**operation_output(operation)})
    return {'counts':counts,'mrr_minor':str(mrr.quantize(Decimal('0.01'))),'arr_minor':str((mrr*12).quantize(Decimal('0.01'))),'currency':'INR','sandbox_active':sandbox_active,'operations_needing_attention':attention[:100]}

@router.post('/platform/billing/tenants/{tenant_id}/operations/{operation_id}/recover')
def recover(tenant_id:uuid.UUID,operation_id:uuid.UUID,body:Recovery,user=Depends(platform_admin),db:Session=Depends(db_session)):
    context(db,'app.tenant_id',tenant_id)
    sub=subscription(db,tenant_id)
    operation=db.scalar(select(BillingOperation).where(BillingOperation.id==operation_id,BillingOperation.tenant_id==tenant_id).with_for_update())
    if not operation or operation.status!='uncertain' or operation.payload['provider']!='razorpay':
        raise HTTPException(409,'Only uncertain Razorpay operations can be recovered')
    adapter=RazorpayProvider()
    try:
        snap=adapter.snapshot(body.provider_ref)
        if operation.kind=='checkout':
            if snap['notes'].get('operation_id')!=str(operation.id) or snap['notes'].get('tenant_id')!=str(tenant_id) or snap['plan_ref']!=operation.payload['plan_ref']:
                raise HTTPException(409,'Provider correlation does not match this operation')
            db.add(ProviderLink(tenant_id=tenant_id,provider='razorpay',provider_ref=body.provider_ref,operation_id=operation.id))
            sub.provider='razorpay';sub.provider_ref=body.provider_ref
            sub.pending_plan_code=operation.payload['plan'];sub.pending_cycle=operation.payload['cycle']
        elif body.provider_ref!=sub.provider_ref:
            raise HTTPException(409,'Provider subscription mismatch')
        elif operation.kind=='schedule':
            scheduled=adapter.request('GET','subscriptions/'+body.provider_ref+'/retrieve_scheduled_changes')
            if scheduled.get('plan_id')!=operation.payload['plan_ref'] and snap['plan_ref']!=operation.payload['plan_ref']:
                raise HTTPException(409,'Provider has not confirmed the requested plan')
            sub.pending_plan_code=operation.payload['plan'];sub.pending_cycle=operation.payload['cycle']
        elif operation.kind=='cancel':
            if snap['status'] not in ('cancelled','completed'): raise HTTPException(409,'Cancellation not yet confirmed; inspect provider before retrying')
            sub.cancel_at_period_end=True
        apply_snapshot(db,sub,snap,'razorpay')
        operation.status='succeeded';operation.error=None;operation.updated_at=now()
        operation.result={'provider_ref':body.provider_ref,'checkout_url':snap.get('checkout_url'),'sandbox':False}
        db.add(PlatformAudit(actor_id=user.id,action='billing.operation.recovered',target_id=operation.id))
        return operation_output(operation)
    except ProviderError as exc:
        raise HTTPException(502,str(exc))
    finally: adapter.close()
