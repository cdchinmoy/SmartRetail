"""Subscription catalog, lifecycle, provider inbox and durable operations."""
import uuid
from alembic import op
from sqlalchemy import text
from app.billing.schema_v2 import Base, Plan
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None
TABLES = ['subscription_plans','subscriptions','billing_operations','billing_provider_links','payment_provider_events','subscription_invoices','billing_notices']

def upgrade():
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind)
    for code, name, monthly, yearly, branches, users, self_service in [
        ('starter','Starter',49900,499000,1,3,True), ('growth','Growth',149900,1499000,3,10,True),
        ('business','Business',399900,3999000,10,50,True), ('enterprise','Enterprise',0,0,100,500,False)]:
        bind.execute(Plan.__table__.insert().values(id=uuid.uuid4(),code=code,name=name,monthly_amount=monthly,yearly_amount=yearly,currency='INR',branch_limit=branches,user_limit=users,features={'branches':True,'team':True,'warehouses':code!='starter'},self_service=self_service,active=True))
    # Existing businesses receive one migration-time trial, not a paid entitlement.
    op.execute("INSERT INTO subscriptions(id,tenant_id,plan_code,cycle,status,trial_ends_at,cancel_at_period_end) SELECT gen_random_uuid(),id,'starter','monthly','trialing',now()+interval '14 days',false FROM tenants")
    for code in ['billing.read','billing.manage']:
        permission_id = uuid.uuid4()
        bind.execute(text('INSERT INTO permissions(id,code) VALUES(:id,:code)'), {'id':permission_id,'code':code})
        bind.execute(text("INSERT INTO role_permissions(role_id,permission_id) SELECT id,:id FROM roles WHERE name='owner'"), {'id':permission_id})
    for table in ['subscriptions','billing_operations','subscription_invoices','billing_notices']:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        match="tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(f'CREATE POLICY billing_isolation ON {table} USING ({match}) WITH CHECK ({match})')
    op.execute('GRANT SELECT, INSERT, UPDATE ON subscription_plans,subscriptions,billing_operations,billing_provider_links TO smartretail_app')
    op.execute('GRANT SELECT, INSERT ON payment_provider_events,subscription_invoices,billing_notices TO smartretail_app')

def downgrade():
    op.execute("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('billing.read','billing.manage'))")
    op.execute("DELETE FROM permissions WHERE code IN ('billing.read','billing.manage')")
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(op.get_bind())
