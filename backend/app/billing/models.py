import uuid
from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, UniqueConstraint, CheckConstraint, DateTime, Integer, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models import Base, Identity

def utcnow():
    return datetime.now(timezone.utc)

class Plan(Identity, Base):
    __tablename__ = 'subscription_plans'
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    monthly_amount: Mapped[int] = mapped_column(Integer)
    yearly_amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default='INR')
    branch_limit: Mapped[int] = mapped_column(Integer)
    user_limit: Mapped[int] = mapped_column(Integer)
    features: Mapped[dict] = mapped_column(JSONB)
    self_service: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    razorpay_monthly_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    razorpay_yearly_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    __table_args__ = (CheckConstraint('monthly_amount >= 0 AND yearly_amount >= 0 AND branch_limit > 0 AND user_limit > 0'),)

class Subscription(Identity, Base):
    __tablename__ = 'subscriptions'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), unique=True)
    plan_code: Mapped[str] = mapped_column(ForeignKey('subscription_plans.code'))
    cycle: Mapped[str] = mapped_column(String(10), default='monthly')
    status: Mapped[str] = mapped_column(String(20), default='trialing')
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_plan_code: Mapped[str | None] = mapped_column(ForeignKey('subscription_plans.code'))
    pending_cycle: Mapped[str | None] = mapped_column(String(10))
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_status: Mapped[str | None] = mapped_column(String(30))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('trialing','active','past_due','grace_period','suspended','canceled','expired')"), CheckConstraint("cycle IN ('monthly','yearly')"))

class BillingOperation(Identity, Base):
    __tablename__ = 'billing_operations'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('tenant_id','request_key'), CheckConstraint("status IN ('pending','running','succeeded','failed','uncertain')"))

class ProviderLink(Identity, Base):
    # Minimal control-plane routing registry. No retail data or customer payment details.
    __tablename__ = 'billing_provider_links'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_ref: Mapped[str] = mapped_column(String(100))
    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    sandbox_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint('provider','provider_ref'),)

class ProviderEvent(Identity, Base):
    __tablename__ = 'payment_provider_events'
    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(150))
    body_hash: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'))
    provider_ref: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('provider','event_id'), UniqueConstraint('provider','body_hash'))

class BillingInvoice(Identity, Base):
    __tablename__ = 'subscription_invoices'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_invoice_id: Mapped[str] = mapped_column(String(100))
    provider_payment_id: Mapped[str] = mapped_column(String(100))
    plan_name: Mapped[str] = mapped_column(String(80))
    cycle: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('provider','provider_invoice_id'), UniqueConstraint('provider','provider_payment_id'), CheckConstraint('amount >= 0'))

class BillingNotice(Identity, Base):
    __tablename__ = 'billing_notices'
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tenants.id'), index=True)
    key: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('tenant_id','key'),)
