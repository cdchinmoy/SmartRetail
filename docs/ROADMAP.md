# Implementation roadmap and milestone status

| Milestone | Scope | Current status / exit requirement |
|---|---|---|
| 1 · Foundation | Auth, tenant creation, memberships, RBAC, RLS, metadata admin, local runtime | Source implemented; local unit/schema/frontend checks passed; integration suite and full-stack startup require execution elsewhere |
| 2 · Subscription engine | Plans, entitlements/quotas, trials, provider abstraction, checkout, verified webhooks, renewal and cancellation | Not implemented; must test duplicate/out-of-order webhook events, expired trials, scheduled downgrades and grace periods |
| 3 · Retail MVP | Business profile/onboarding, catalog, customers, stock ledger, POS, invoices and dashboard | Not implemented; must prove no oversell or double stock deduction under concurrent and duplicate checkout |
| 4 · Expansion | Suppliers, purchasing, receipts, expenses, staff invitations, branch assignments, reports and transfers | Not implemented; test composite tenant FKs, multi-branch permissions and stock reconciliation |
| 5 · Commercial launch | Marketing/pricing, verified signup, hardened infrastructure, observability, backups, docs and review | Not implemented; security review, restore drill, load tests, monitoring and deployment rollback are release gates |

## Milestone 1 delivered components

- Modular FastAPI backend and React workspace.
- PostgreSQL schema and initial Alembic migration with frozen schema snapshot.
- Tenant and membership uniqueness, composite warehouse/branch tenant relationship.
- Parameterized tenant-aware repository and forced RLS policies.
- Argon2 password hashing; JWT access/refresh; rotation, replay revocation and logout.
- Exact-Origin protection for cookie refresh/logout; Redis auth throttling.
- Owner/manager/cashier catalog and server-side permission checks.
- Retry-safe, transactionally created workspace, membership, main branch and audit event.
- Branch list/create/read; warehouse creation; membership add/revoke; owner audit list.
- Platform metadata overview/list and audited suspend/reactivate.
- Explicit demo seed for two unrelated businesses and one platform operator.
- Compose and CI definitions; lockfiles; OpenAPI export; unit and integration tests.

## Remaining foundation hardening

Run the five database integration tests and full Docker startup. Verify browser login, refresh, workspace switching and permission-specific UI. Implement email/phone verification, password reset, optional MFA, refresh-family cleanup, invitation lifecycle, finer branch-level scope, custom role management, account abuse limits and structured error logging for unexpected exceptions. Add metrics and tracing with tenant privacy controls. These are not silently represented as completed authentication features.

The demo permits account creation without email verification. Do not open self-service signup to the public before verification and abuse controls are implemented. The platform UI has no support-access escalation; define an explicit tenant-approved, scoped, expiring support grant before adding it.

## Future backend boundaries

Add `billing/{provider,service,repository,router,schemas}.py`, `catalog`, `inventory`, `sales`, `purchasing`, `customers`, `reports`, and `jobs` only with real functionality. Shared core remains limited to configuration, database, context and observability; do not turn it into a catch-all for business logic. Extract services only when measured scaling or ownership boundaries justify the operational cost.

## Future frontend areas

Separate public marketing/auth, tenant operations and platform control-plane route trees. Retain query keys scoped by tenant ID. Add feature-level modules for POS/catalog/inventory/customers/purchases/reports/billing. Adopt validated forms and consistent loading/empty/error states; never hide authorization solely in the UI.

## Run and test

See the root README for exact Compose commands. The current validation evidence is in `TEST_STATUS.md`. Payment-webhook, subscription-expiry and concurrent-POS tests are **not applicable yet**, rather than passed or replaced with placeholders.
