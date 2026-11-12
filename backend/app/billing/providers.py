"""Provider boundary. Only provider-verified captured payments produce paid periods."""
import calendar
import copy
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Protocol
import httpx
from app.core.config import settings

class ProviderError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain

class Provider(Protocol):
    def execute(self, kind: str, payload: dict, state: dict) -> dict: ...

def next_period(start: datetime, cycle: str) -> datetime:
    months = 1 if cycle == 'monthly' else 12
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year,month)[1]))

def valid_signature(body: bytes, signature: str, secrets: list[str]) -> bool:
    return any(secret and hmac.compare_digest(hmac.new(secret.encode(),body,hashlib.sha256).hexdigest(),signature) for secret in secrets)

class SandboxProvider:
    """Deterministic local simulation. No network call and no money is collected."""
    def execute(self, kind, payload, state):
        if settings.environment != 'development' or settings.billing_provider != 'sandbox':
            raise ProviderError('Sandbox is disabled')
        data = copy.deepcopy(state)
        if kind == 'checkout':
            data = {'id':'sandbox_'+payload['operation_id'], 'status':'created', 'plan_ref':payload['plan_ref'], 'plan':payload['plan'], 'cycle':payload['cycle'], 'amount':payload['amount'], 'currency':payload['currency'], 'invoices':[], 'cancel_pending':False, 'notes':{'operation_id':payload['operation_id'],'tenant_id':payload['tenant_id']}}
        elif kind == 'schedule':
            data['scheduled']={k:payload[k] for k in ['plan_ref','plan','cycle','amount','currency']}
        elif kind == 'cancel':
            data['cancel_pending']=True
        elif kind == 'sandbox_fail':
            data['status']='pending'
        elif kind == 'sandbox_charge':
            if data.get('cancel_pending'):
                raise ProviderError('Subscription is scheduled for cancellation')
            previous_end=data.get('current_end',0)
            now=int(time.time())
            if previous_end > now:
                raise ProviderError('Current paid period has not ended; duplicate charge refused')
            data.update(data.pop('scheduled',{}))
            start=datetime.fromtimestamp(max(previous_end,now),timezone.utc)
            end=next_period(start,data['cycle'])
            invoice={'id':'sinv_'+payload['operation_id'],'payment_id':'spay_'+payload['operation_id'], 'amount':data['amount'],'currency':data['currency'], 'start':int(start.timestamp()),'end':int(end.timestamp()),'paid_at':now,'plan_name':data['plan'], 'captured':True}
            data['invoices'].append(invoice)
            data.update(status='active',current_start=invoice['start'],current_end=invoice['end'])
        elif kind != 'reconcile':
            raise ProviderError('Unsupported sandbox operation')
        if data.get('cancel_pending') and data.get('current_end',0) <= time.time():
            data['status']='cancelled'
        return data

class RazorpayProvider:
    def __init__(self, client=None):
        self.client=client or httpx.Client(base_url='https://api.razorpay.com/v1/',auth=(settings.razorpay_key_id,settings.razorpay_key_secret),timeout=15)

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            response=self.client.request(method,path,**kwargs)
        except httpx.HTTPError:
            raise ProviderError('Provider connection failed',uncertain=method!='GET')
        if response.status_code >= 400:
            raise ProviderError(f'Provider returned HTTP {response.status_code}',uncertain=method!='GET' and response.status_code>=500)
        try:
            return response.json()
        except ValueError:
            raise ProviderError('Invalid provider response',uncertain=method!='GET')

    def verify_plan(self, payload):
        plan=self.request('GET','plans/'+payload['plan_ref'])
        expected_period='monthly' if payload['cycle']=='monthly' else 'yearly'
        item=plan.get('item',{})
        if (plan.get('period'),plan.get('interval'),item.get('amount'),item.get('currency')) != (expected_period,1,payload['amount'],payload['currency']):
            raise ProviderError('Provider plan price, currency or interval differs from the server catalog')

    def snapshot(self, ref):
        sub=self.request('GET','subscriptions/'+ref)
        invoices=[]
        current_refunded=False
        for offset in range(0,10000,100):
            batch=self.request('GET','invoices',params={'subscription_id':ref,'count':100,'skip':offset}).get('items',[])
            for inv in batch:
                if inv.get('subscription_id') != ref or inv.get('status')!='paid' or not inv.get('payment_id'):
                    continue
                payment=self.request('GET','payments/'+inv['payment_id'])
                start,end=inv.get('billing_start'),inv.get('billing_end')
                if payment.get('amount_refunded',0) and end==sub.get('current_end'):
                    current_refunded=True
                if not start or not end or end<=start or payment.get('status')!='captured' or payment.get('amount_refunded',0):
                    continue
                if payment.get('invoice_id')!=inv['id'] or payment.get('amount')!=inv.get('amount_paid') or payment.get('currency')!=inv.get('currency'):
                    continue
                invoices.append({'id':inv['id'],'payment_id':payment['id'],'amount':inv['amount_paid'],'currency':inv['currency'],'start':start,'end':end,'paid_at':inv.get('paid_at') or payment['created_at'],'plan_name':(inv.get('description') or 'Subscription')[:80],'captured':True})
            if len(batch)<100:
                break
        else:
            raise ProviderError('Invoice history pagination limit reached; operator reconciliation required')
        return {'id':sub['id'],'status':sub['status'],'plan_ref':sub['plan_id'],'current_start':sub.get('current_start'),'current_end':sub.get('current_end'),'invoices':invoices,'checkout_url':sub.get('short_url'),'notes':sub.get('notes',{}),'cancel_pending':False,'current_refunded':current_refunded}

    def execute(self,kind,payload,state):
        ref=state.get('id')
        if kind in ('checkout','schedule'):
            self.verify_plan(payload)
        if kind=='checkout':
            sub=self.request('POST','subscriptions',json={'plan_id':payload['plan_ref'],'total_count':120 if payload['cycle']=='monthly' else 10,'quantity':1,'customer_notify':1,'notes':{'tenant_id':payload['tenant_id'],'operation_id':payload['operation_id']}})
            # Creation response is enough to publish the hosted link. Never grant access here.
            return {'id':sub['id'],'status':sub['status'],'plan_ref':sub['plan_id'],'checkout_url':sub.get('short_url'),'notes':sub.get('notes',{}),'invoices':[]}
        if kind=='schedule':
            self.request('PATCH','subscriptions/'+ref,json={'plan_id':payload['plan_ref'],'schedule_change_at':'cycle_end','customer_notify':True})
            # Do not follow a successful mutation with a fallible GET before recording success.
            return {'id':ref,'scheduled':True,'invoices':[]}
        if kind=='cancel':
            self.request('POST','subscriptions/'+ref+'/cancel',json={'cancel_at_cycle_end':1 if payload.get('cancel_at_cycle_end') else 0})
            return {'id':ref,'cancel_pending':True,'invoices':[]}
        if kind=='reconcile':
            return self.snapshot(ref)
        raise ProviderError('Unsupported provider operation')

def provider_for(name):
    if name=='sandbox': return SandboxProvider()
    if name=='razorpay': return RazorpayProvider()
    raise ProviderError('Unknown billing provider')
