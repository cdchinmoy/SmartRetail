# Verification record · 12 November 2026

| Check | Result | Scope |
|---|---|---|
| Backend suite | **43 passed** | Real PostgreSQL 16.2 over TCP, online Alembic migrations, restricted runtime database role |
| Tenant isolation | Passed | Cross-tenant API and raw SQL denials, pooled context reset, cashier permissions |
| Subscription lifecycle | Passed | Trial expiry, captured-payment activation, cycle-end changes/cancellation, grace and suspension |
| Billing safety | Passed | Idempotency, signed duplicate/replayed webhooks, concurrent branch quota, uncertain provider outcomes, sandbox exclusion in production |
| Provider contract | Passed with mocks | Razorpay plan validation, payment capture validation and uncertain network responses |
| Frontend | TypeScript and Vite production build passed | No interactive browser QA |
| Setup helper | 3 tests passed | Generates missing secrets without replacing existing values |

The backend suite emits one third-party Starlette/httpx deprecation warning. Local database tests invoke the worker directly; they do not establish Celery/Redis delivery. CI also starts Compose services and runs an HTTP-to-Celery sandbox payment smoke test. See the pull request's Actions result for that separate verification.

Real Razorpay test/live transactions, merchant payment-method eligibility, browser checkout, production deployment, backup restoration and load testing remain unverified. Sandbox payments never move money. Receipts are not GST tax invoices. See [Milestone 2](MILESTONE_2.md) for setup and release checks.
