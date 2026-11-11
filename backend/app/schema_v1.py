import uuid
from datetime import datetime
from sqlalchemy import Boolean, String, ForeignKey, UniqueConstraint, CheckConstraint, DateTime, Text, ForeignKeyConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

class Base(DeclarativeBase):
    pass
class Identity:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
class User(Identity, Base):
    __tablename__ = 'users'
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
class Tenant(Identity, Base):
    __tablename__ = 'tenants'
    name: Mapped[str] = mapped_column(String(100))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(20), default='active')
    creation_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint('owner_id', 'creation_key'), CheckConstraint("status in ('active','suspended')"))
class Role(Identity, Base):
    __tablename__ = 'roles'
    name: Mapped[str] = mapped_column(String(30), unique=True)
class Permission(Identity, Base):
    __tablename__ = 'permissions'
    code: Mapped[str] = mapped_column(String(60), unique=True)
class RolePermission(Base):
    __tablename__ = 'role_permissions'
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('roles.id'), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('permissions.id'), primary_key=True)
class Membership(Identity, Base):
    __tablename__ = 'tenant_memberships'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('roles.id'))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'user_id'),)
class Branch(Identity, Base):
    __tablename__ = 'branches'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'))
    name: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('tenant_id', 'name'), UniqueConstraint('tenant_id', 'id'))
class Warehouse(Identity, Base):
    __tablename__ = 'warehouses'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(100))
    __table_args__ = (ForeignKeyConstraint(['tenant_id','branch_id'], ['branches.tenant_id','branches.id']), UniqueConstraint('tenant_id','branch_id','name'))
class RefreshSession(Identity, Base):
    __tablename__ = 'refresh_sessions'
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
class Audit(Identity, Base):
    __tablename__ = 'tenant_audit_logs'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
class PlatformAudit(Identity, Base):
    __tablename__ = 'platform_audit_logs'
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
