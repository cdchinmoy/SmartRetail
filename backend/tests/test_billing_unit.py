import hashlib
import hmac
from datetime import datetime, timezone
import httpx
import pytest
from app.billing.providers import next_period, valid_signature, SandboxProvider, RazorpayProvider, ProviderError
from app.core.config import Settings, settings

@pytest.mark.parametrize('start,cycle,expected',[
    ('2024-01-31','monthly','2024-02-29'),('2025-01-31','monthly','2025-02-28'),
    ('2024-02-29','yearly','2025-02-28'),('2025-12-15','monthly','2026-01-15')])
def test_calendar_periods(start,cycle,expected):
    assert str(next_period(datetime.fromisoformat(start).replace(tzinfo=timezone.utc),cycle).date())==expected

def test_raw_body_signature_and_secret_rotation():
    body=b'{"event": "subscription.charged"}'
    signature=hmac.new(b'old-key',body,hashlib.sha256).hexdigest()
    assert valid_signature(body,signature,['new-key','old-key'])
    assert not valid_signature(body.replace(b' ',b''),signature,['old-key'])
    assert not valid_signature(body,signature,['wrong-key'])
    assert not valid_signature(body,'', [''])

def test_production_refuses_sandbox():
    with pytest.raises(ValueError):
        Settings(database_url='postgresql://unused',jwt_secret='a'*32,environment='production',billing_provider='sandbox')

def test_razorpay_requires_credentials():
    with pytest.raises(ValueError):
        Settings(database_url='postgresql://unused',jwt_secret='a'*32,billing_provider='razorpay',razorpay_key_id='',razorpay_key_secret='',razorpay_webhook_secret='')

def test_sandbox_never_activates_from_checkout_and_rejects_double_charge():
    provider=SandboxProvider()
    payload={'operation_id':'one','tenant_id':'tenant','plan_ref':'sandbox:growth:monthly','plan':'growth','cycle':'monthly','amount':149900,'currency':'INR'}
    created=provider.execute('checkout',payload,{})
    assert created['status']=='created' and created['invoices']==[]
    paid=provider.execute('sandbox_charge',{'operation_id':'two'},created)
    assert paid['status']=='active' and len(paid['invoices'])==1
    assert created['invoices']==[]
    with pytest.raises(ProviderError): provider.execute('sandbox_charge',{'operation_id':'three'},paid)

def test_provider_plan_validation_blocks_price_tampering():
    client=httpx.Client(base_url='https://api.razorpay.com/v1/',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'period':'monthly','interval':1,'item':{'amount':1,'currency':'INR'}})))
    adapter=RazorpayProvider(client)
    with pytest.raises(ProviderError,match='differs'):
        adapter.execute('checkout',{'plan_ref':'plan_test','cycle':'monthly','amount':49900,'currency':'INR'}, {})
    adapter.close()

def test_mutation_timeout_is_uncertain():
    def fail(request): raise httpx.ReadTimeout('timeout')
    adapter=RazorpayProvider(httpx.Client(base_url='https://api.razorpay.com/v1/',transport=httpx.MockTransport(fail)))
    with pytest.raises(ProviderError) as exc: adapter.request('POST','subscriptions',json={})
    assert exc.value.uncertain
    with pytest.raises(ProviderError) as exc: adapter.request('GET','subscriptions/sub_x')
    assert not exc.value.uncertain
    adapter.close()

def test_snapshot_requires_captured_invoice_matched_payment():
    def respond(request):
        if request.url.path.endswith('/subscriptions/sub_x'):
            data={'id':'sub_x','status':'active','plan_id':'plan_x','current_start':100,'current_end':200}
        elif request.url.path.endswith('/invoices'):
            data={'items':[{'id':'inv_x','subscription_id':'sub_x','status':'paid','payment_id':'pay_x','billing_start':100,'billing_end':200,'amount_paid':49900,'currency':'INR','paid_at':101}]}
        else: data={'id':'pay_x','status':'authorized','invoice_id':'inv_x','amount':49900,'currency':'INR','created_at':101}
        return httpx.Response(200,json=data)
    adapter=RazorpayProvider(httpx.Client(base_url='https://api.razorpay.com/v1/',transport=httpx.MockTransport(respond)))
    assert adapter.snapshot('sub_x')['invoices']==[]
    adapter.close()


def test_v2_schema_does_not_mutate_v1_migration_metadata():
    from app.schema_v1 import Base as V1
    from app.billing.schema_v2 import Base as V2
    assert 'subscriptions' not in V1.metadata.tables
    assert 'subscriptions' in V2.metadata.tables
    assert V1.metadata is not V2.metadata
