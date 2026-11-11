"""Foundation schema, RBAC and fail-closed RLS. Immutable v1 schema snapshot."""
import uuid
from alembic import op
from sqlalchemy import text
from app.schema_v1 import Base
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    # Catalog roles are application RBAC roles, unrelated to PostgreSQL login roles.
    permissions = {code: uuid.uuid4() for code in ['branches.read','branches.write','members.manage','audit.read']}
    for code, ident in permissions.items():
        bind.execute(text('INSERT INTO permissions (id,code) VALUES (:id,:code)'), {'id':ident,'code':code})
    for name, codes in {'owner': list(permissions), 'manager':['branches.read','branches.write'], 'cashier':['branches.read']}.items():
        ident = uuid.uuid4()
        bind.execute(text('INSERT INTO roles (id,name) VALUES (:id,:name)'), {'id':ident,'name':name})
        for code in codes:
            bind.execute(text('INSERT INTO role_permissions (role_id,permission_id) VALUES (:r,:p)'), {'r':ident,'p':permissions[code]})
    tenant_match = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    for table in ['tenant_memberships','branches','warehouses','tenant_audit_logs']:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        if table == 'tenant_memberships':
            op.execute(f"CREATE POLICY membership_read ON {table} FOR SELECT USING ({tenant_match} OR user_id = nullif(current_setting('app.user_id', true), '')::uuid)")
            for command in ['INSERT','UPDATE','DELETE']:
                clauses = f'WITH CHECK ({tenant_match})' if command == 'INSERT' else f'USING ({tenant_match})'
                if command == 'UPDATE':
                    clauses += f' WITH CHECK ({tenant_match})'
                op.execute(f'CREATE POLICY membership_{command.lower()} ON {table} FOR {command} {clauses}')
        else:
            op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({tenant_match}) WITH CHECK ({tenant_match})')
    # Role is provisioned separately; never connect the API with the migration role.
    op.execute('GRANT USAGE ON SCHEMA public TO smartretail_app')
    op.execute('GRANT SELECT, INSERT, UPDATE ON users, tenants, tenant_memberships, branches, warehouses, refresh_sessions TO smartretail_app')
    op.execute('GRANT SELECT ON roles, permissions, role_permissions TO smartretail_app')
    op.execute('GRANT SELECT, INSERT ON tenant_audit_logs, platform_audit_logs TO smartretail_app')

def downgrade():
    Base.metadata.drop_all(op.get_bind())
