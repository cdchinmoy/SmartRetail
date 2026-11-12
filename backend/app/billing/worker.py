"""Durable DB outbox, processed by Celery Beat. No provider mutation in HTTP requests."""
import logging
import uuid
from datetime import timedelta
from sqlalchemy import select, text
from app.core.db import SessionLocal, engine, context
from app.billing.models import Subscription, BillingOperation, ProviderLink
from app.billing.providers import provider_for, ProviderError
from app.billing.service import subscription, tick, enqueue, apply_snapshot, now
from app.models import Tenant

log=logging.getLogger('smartretail.billing')

def process_operation(tenant_id, operation_id):
    # Caller serializes workers per tenant. Persist intent before any external side effect.
    with SessionLocal.begin() as db:
        context(db,'app.tenant_id',tenant_id)
        operation=db.get(BillingOperation,operation_id)
        if operation.status!='pending' or operation.available_at>now(): return
        operation.status='running';operation.attempts+=1;operation.updated_at=now()
        kind=operation.kind
        provider_name=operation.payload['provider']
    adapter=None
    try:
        with SessionLocal.begin() as db:
            context(db,'app.tenant_id',tenant_id)
            sub=subscription(db,tenant_id)
            operation=db.get(BillingOperation,operation_id)
            link=db.scalar(select(ProviderLink).where(ProviderLink.tenant_id==tenant_id,ProviderLink.provider==provider_name,ProviderLink.provider_ref==sub.provider_ref)) if sub.provider_ref else None
            state=(link.sandbox_state if provider_name=='sandbox' else {'id':link.provider_ref}) if link else {}
            adapter=provider_for(provider_name)
            payload={**operation.payload,'cancel_at_cycle_end':bool(sub.period_end and sub.period_end>now())}
            result=adapter.execute(kind,payload,state)
            if kind=='checkout':
                if result.get('notes',{}).get('operation_id')!=str(operation_id):
                    raise ProviderError('Provider correlation mismatch',uncertain=True)
                link=ProviderLink(tenant_id=tenant_id,provider=provider_name,provider_ref=result['id'],operation_id=operation_id,sandbox_state=result if provider_name=='sandbox' else {})
                db.add(link)
                sub.provider=provider_name;sub.provider_ref=result['id'];sub.provider_status=result['status']
                sub.pending_plan_code=payload['plan'];sub.pending_cycle=payload['cycle']
                sub.cancel_at_period_end=False
            if kind=='schedule':
                sub.pending_plan_code=payload['plan'];sub.pending_cycle=payload['cycle']
            if kind=='cancel': sub.cancel_at_period_end=True
            if provider_name=='sandbox' and link:
                link.sandbox_state=result
            if 'status' in result: apply_snapshot(db,sub,result,provider_name)
            operation.status='succeeded';operation.error=None;operation.updated_at=now()
            # No full provider payloads, PII or payment credentials exposed to browser.
            operation.result={'provider_ref':result['id'],'checkout_url':result.get('checkout_url'),'sandbox':provider_name=='sandbox'}
    except Exception as exc:
        with SessionLocal.begin() as db:
            context(db,'app.tenant_id',tenant_id)
            operation=db.get(BillingOperation,operation_id)
            safe_retry=kind=='reconcile' or provider_name=='sandbox'
            permanent_sandbox_error=provider_name=='sandbox' and isinstance(exc,ProviderError) and not exc.uncertain
            if safe_retry and not permanent_sandbox_error and operation.attempts<8:
                operation.status='pending'
                operation.available_at=now()+timedelta(seconds=min(3600,30*2**operation.attempts))
            else:
                operation.status='uncertain' if not safe_retry and (not isinstance(exc,ProviderError) or exc.uncertain) else 'failed'
            operation.error=str(exc) if isinstance(exc,ProviderError) else 'Billing processing failed; operator review required'
            operation.updated_at=now()
        log.warning('billing operation=%s kind=%s error_type=%s',operation_id,kind,type(exc).__name__)
    finally:
        if adapter and hasattr(adapter,'close'): adapter.close()

def process_tenant(tenant_id):
    # Session advisory lock is released explicitly before the pooled connection is returned.
    with engine.connect() as connection:
        key='billing-worker:'+str(tenant_id)
        acquired=connection.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),{'key':key}).scalar()
        if not acquired: return
        try:
            with SessionLocal.begin() as db:
                context(db,'app.tenant_id',tenant_id)
                sub=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant_id).with_for_update())
                if not sub: return
                tick(db,sub)
                for operation in db.scalars(select(BillingOperation).where(BillingOperation.tenant_id==tenant_id,BillingOperation.status=='running',BillingOperation.updated_at<now()-timedelta(minutes=10))):
                    operation.status='pending' if operation.kind=='reconcile' or operation.payload['provider']=='sandbox' else 'uncertain'
                    operation.error='Worker interrupted; reconcile provider state before retrying mutation'
                operations=list(db.scalars(select(BillingOperation.id).where(BillingOperation.tenant_id==tenant_id,BillingOperation.status=='pending',BillingOperation.available_at<=now()).order_by(BillingOperation.created_at).limit(20)))
            for operation_id in operations:
                process_operation(tenant_id,operation_id)
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key,0))'),{'key':key})
            connection.commit()

def sweep():
    with SessionLocal() as db:
        tenant_ids=list(db.scalars(select(Tenant.id)))
    for tenant_id in tenant_ids:
        try:
            with SessionLocal.begin() as db:
                context(db,'app.tenant_id',tenant_id)
                sub=db.scalar(select(Subscription).where(Subscription.tenant_id==tenant_id))
                if sub and sub.provider_ref:
                    # Catch missed webhooks. Each 5-minute reconciliation window has one request key.
                    window=int(now().timestamp())//300
                    key=uuid.uuid5(uuid.NAMESPACE_URL,f'reconcile:{tenant_id}:{window}')
                    enqueue(db,tenant_id,key,'reconcile',{})
            process_tenant(tenant_id)
        except Exception as exc:
            log.warning('billing sweep error_type=%s',type(exc).__name__)

if __name__=='__main__': sweep()
