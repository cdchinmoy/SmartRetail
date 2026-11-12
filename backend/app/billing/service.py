import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from fastapi import HTTPException
from app.core.config import settings
from app.models import Branch, Membership, Tenant, Audit
from app.billing.models import Plan, Subscription, BillingOperation, BillingInvoice, BillingNotice

BUSY=('pending','running','uncertain')

def now(): return datetime.now(timezone.utc)

def plan_by_code(db,code):
    plan=db.scalar(select(Plan).where(Plan.code==code))
    if not plan: raise HTTPException(404,'Plan not found')
    return plan

def create_trial(db,tenant_id):
    sub=Subscription(tenant_id=tenant_id,plan_code='starter',cycle='monthly',status='trialing',trial_ends_at=now()+timedelta(days=settings.trial_days))
    db.add(sub);db.flush()
    return sub

def subscription(db,tenant_id):
    sub=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant_id).with_for_update())
    if not sub: raise HTTPException(409,'Subscription missing; apply the billing migration')
    return sub

def notice(db,sub,key,message):
    if not db.scalar(select(BillingNotice.id).where(BillingNotice.tenant_id==sub.tenant_id,BillingNotice.key==key)):
        db.add(BillingNotice(tenant_id=sub.tenant_id,key=key,message=message))
        db.flush()

def tick(db,sub,at=None):
    at=at or now()
    if sub.status=='trialing':
        if at>=sub.trial_ends_at:
            sub.status='expired'
            notice(db,sub,'trial.expired','Your trial has ended. Choose a plan to resume creating business records. Existing data remains readable.')
        elif sub.trial_ends_at-at<=timedelta(days=3):
            notice(db,sub,'trial.ending','Your trial ends within three days. Select a subscription to continue without interruption.')
    elif sub.period_end and at>=sub.period_end:
        if sub.cancel_at_period_end or sub.provider_status in ('cancelled','completed'):
            sub.status='canceled'
        elif sub.status not in ('suspended','expired','canceled'):
            sub.past_due_since=sub.past_due_since or sub.period_end
            sub.grace_ends_at=sub.grace_ends_at or sub.period_end+timedelta(days=settings.grace_days)
            sub.status='grace_period' if at<sub.grace_ends_at else 'suspended'
            notice(db,sub,'renewal.'+str(sub.period_end.timestamp()),'Renewal is not confirmed. Check your payment method; access is restricted after the grace period.')
    return sub

def usage(db,tenant_id):
    return {'branches':db.scalar(select(func.count()).select_from(Branch).where(Branch.tenant_id==tenant_id)), 'users':db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id==tenant_id,Membership.active.is_(True)))}

def entitlements(db,sub):
    tick(db,sub)
    plan=plan_by_code(db,sub.plan_code)
    counts=usage(db,sub.tenant_id)
    can_write=sub.status in ('trialing','active','grace_period') or (sub.status=='past_due' and bool(sub.period_end and sub.period_end>now()))
    if sub.provider=='sandbox' and settings.environment!='development':
        can_write=False
    return {'can_write':can_write, 'features':plan.features, 'limits':{'branches':plan.branch_limit,'users':plan.user_limit}, 'usage':counts, 'over_limit':[k for k,limit in [('branches',plan.branch_limit),('users',plan.user_limit)] if counts[k]>limit]}

def require_capacity(db,tenant_id,resource=None,feature=None):
    # Lock subscription before counting/inserting resources: two concurrent creates cannot pass the same quota.
    sub=subscription(db,tenant_id)
    rights=entitlements(db,sub)
    if not rights['can_write']: raise HTTPException(402,'Subscription requires payment; existing data remains available')
    if feature and not rights['features'].get(feature,False): raise HTTPException(403,'Feature is not included in this plan')
    if resource and rights['usage'][resource]>=rights['limits'][resource]: raise HTTPException(409,f'Plan {resource} limit reached; upgrade or reduce usage')
    return sub

def catalog_payload(plan,cycle,provider):
    ref=f'sandbox:{plan.code}:{cycle}' if provider=='sandbox' else getattr(plan,'razorpay_'+cycle+'_id')
    if not ref: raise HTTPException(409,'Payment provider plan is not configured by the platform operator')
    return {'plan':plan.code,'cycle':cycle,'plan_ref':ref,'amount':getattr(plan,cycle+'_amount'),'currency':plan.currency}

def enqueue(db,tenant_id,key,kind,payload,actor=None):
    sub=subscription(db,tenant_id)
    existing=db.scalar(select(BillingOperation).where(BillingOperation.tenant_id==tenant_id,BillingOperation.request_key==key))
    if existing:
        if existing.kind!=kind or existing.payload.get('request')!=payload:
            raise HTTPException(409,'Idempotency key reused with a different request')
        return existing
    tick(db,sub)
    if kind!='reconcile' and db.scalar(select(BillingOperation.id).where(BillingOperation.tenant_id==tenant_id,BillingOperation.status.in_(BUSY),BillingOperation.kind!='reconcile')):
        raise HTTPException(409,'A billing change is still pending; resolve it before starting another')
    name=sub.provider or settings.billing_provider
    data={'request':payload, 'provider':name,'tenant_id':str(tenant_id)}
    if kind in ('checkout','schedule'):
        plan=plan_by_code(db,payload['plan'])
        if not plan.active or not plan.self_service: raise HTTPException(409,'Contact the platform operator for this plan')
        if kind=='checkout' and sub.provider_ref and sub.provider_status not in ('cancelled','completed','expired'):
            raise HTTPException(409,'An existing provider subscription must be reconciled or canceled before creating another')
        if kind=='schedule' and (sub.status!='active' or sub.cancel_at_period_end or sub.pending_plan_code):
            raise HTTPException(409,'Plan changes require an active subscription without another scheduled change')
        if kind=='schedule' and plan.code==sub.plan_code and payload['cycle']==sub.cycle:
            raise HTTPException(409,'This plan and billing cycle are already active')
        data.update(catalog_payload(plan,payload['cycle'],name))
    if kind in ('cancel','schedule','reconcile','sandbox_charge','sandbox_fail') and not sub.provider_ref:
        raise HTTPException(409,'No provider subscription to update')
    if kind=='cancel' and sub.cancel_at_period_end:
        raise HTTPException(409,'Cancellation is already scheduled')
    if kind.startswith('sandbox_') and (name!='sandbox' or settings.environment!='development'):
        raise HTTPException(404,'Sandbox controls unavailable')
    operation=BillingOperation(tenant_id=tenant_id,request_key=key,kind=kind,payload=data)
    db.add(operation);db.flush()
    operation.payload={**data,'operation_id':str(operation.id)}
    if actor:
        db.add(Audit(tenant_id=tenant_id,actor_id=actor,action='billing.'+kind+'.requested',target_id=operation.id))
    return operation

def apply_snapshot(db,sub,snapshot,provider):
    if snapshot['id']!=sub.provider_ref: return
    at=now()
    ref=snapshot.get('plan_ref')
    if provider=='sandbox':
        parts=(ref or '').split(':')
        plan=plan_by_code(db,parts[1]) if len(parts)==3 else None
        cycle=parts[2] if len(parts)==3 else None
    else:
        plan=db.scalar(select(Plan).where((Plan.razorpay_monthly_id==ref)|(Plan.razorpay_yearly_id==ref)))
        cycle='monthly' if plan and plan.razorpay_monthly_id==ref else 'yearly'
    if not plan or cycle not in ('monthly','yearly'):
        raise ValueError('Provider subscription references an unrecognized catalog plan')
    paid_current=None
    for inv in snapshot.get('invoices',[]):
        if not inv.get('captured') or inv['end']<=inv['start'] or inv['currency']!=plan.currency:
            continue
        start=datetime.fromtimestamp(inv['start'],timezone.utc);end=datetime.fromtimestamp(inv['end'],timezone.utc)
        if not db.scalar(select(BillingInvoice.id).where(BillingInvoice.provider==provider,BillingInvoice.provider_invoice_id==inv['id'])):
            db.add(BillingInvoice(tenant_id=sub.tenant_id,provider=provider,provider_invoice_id=inv['id'],provider_payment_id=inv['payment_id'],plan_name=inv.get('plan_name',plan.name),cycle=cycle,amount=inv['amount'],currency=inv['currency'],period_start=start,period_end=end,paid_at=datetime.fromtimestamp(inv['paid_at'],timezone.utc)))
            db.flush()
        if inv['start']==snapshot.get('current_start') and inv['end']==snapshot.get('current_end') and inv['amount']==getattr(plan,cycle+'_amount'):
            paid_current=(start,end)
    sub.provider_status=snapshot['status']
    sub.synced_at=at
    if paid_current and (not sub.period_end or paid_current[1]>=sub.period_end):
        sub.period_start,sub.period_end=paid_current
        sub.plan_code,sub.cycle=plan.code,cycle
        if sub.pending_plan_code==plan.code and sub.pending_cycle==cycle:
            sub.pending_plan_code=None;sub.pending_cycle=None
        sub.status='active'
        sub.past_due_since=None;sub.grace_ends_at=None
    if snapshot.get('current_refunded'):
        sub.status='suspended'
    elif snapshot['status'] in ('halted','paused'):
        sub.status='suspended'
    elif snapshot['status']=='pending':
        sub.status='past_due'
        sub.past_due_since=sub.past_due_since or at
        anchor=sub.period_end or at
        sub.grace_ends_at=sub.grace_ends_at or anchor+timedelta(days=settings.grace_days)
        if not sub.period_end:
            sub.status='suspended'
        elif at>=anchor:
            sub.status='grace_period' if at<sub.grace_ends_at else 'suspended'
    elif snapshot['status'] in ('cancelled','completed','expired'):
        sub.cancel_at_period_end=True
        if not sub.period_end or at>=sub.period_end: sub.status='canceled' if snapshot['status']!='expired' else 'expired'
    tick(db,sub,at)
