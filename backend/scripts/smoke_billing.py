"""Disposable-environment smoke check through the real HTTP API and Celery scheduler.
Creates a test account and tenant. Never run this against a live payment configuration.
"""
import time
import uuid
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000/api/v1',timeout=10) as client:
    catalog=client.get('/subscriptions/plans');catalog.raise_for_status()
    if catalog.json()['provider']!='sandbox':
        raise RuntimeError('Smoke test requires sandbox billing')
    auth=client.post('/auth/register',json={'email':f'smoke-{uuid.uuid4()}@example.com','password':str(uuid.uuid4())+str(uuid.uuid4())})
    auth.raise_for_status()
    client.headers['Authorization']='Bearer '+auth.json()['access_token']
    created=client.post('/tenants',headers={'Idempotency-Key':str(uuid.uuid4())},json={'name':'Disposable billing smoke test'})
    created.raise_for_status();client.headers['X-Tenant-ID']=created.json()['id']
    checkout=client.post('/billing/checkout',headers={'Idempotency-Key':str(uuid.uuid4())},json={'plan':'growth','cycle':'monthly'})
    checkout.raise_for_status()
    def wait_for(field,value=None):
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            response=client.get('/subscriptions/current');response.raise_for_status()
            current=response.json()
            if (current.get(field)==value if value is not None else bool(current.get(field))):return
            time.sleep(2)
        raise RuntimeError('Background billing operation did not complete within 100 seconds')
    wait_for('provider_ref')
    payment=client.post('/billing/sandbox/charge',headers={'Idempotency-Key':str(uuid.uuid4())});payment.raise_for_status()
    wait_for('status','active')
    invoices=client.get('/billing/invoices');invoices.raise_for_status()
    assert len(invoices.json())==1 and invoices.json()[0]['amount']==149900
    print('PASS: real API -> durable operation -> Celery scheduler/worker -> active sandbox subscription and invoice')
