# Verification record · 11 November 2026

## Executed in this environment

| Check | Result | Practical limit |
|---|---|---|
| `pytest -q` | **12 passed, 5 skipped** | Integration tests skipped without RUN_DB_TESTS=1; no API/database isolation claim |
| Password hashing | Passed | Salt uniqueness, valid/invalid password verification |
| JWT checks | Passed | Access/refresh round trips, type confusion, expiry, malformed/unsigned/wrong-key tokens |
| Request protections | Passed | Reject body tenant-ID injection; exact-Origin guard; auth rate-limit/reachability behavior with mocked Redis |
| PostgreSQL schema execution | Passed on PostgreSQL 16.2 standalone backend | Runs v1 table/index/constraint/policy/grant/seed DDL and checks RLS flags/RBAC seed; **does not test behavioral RLS** |
| Frontend | **TypeScript check and Vite production build passed** | No interactive browser QA; third-party `use client` and pure-comment bundler warnings were nonfatal |
| OpenAPI | Generated successfully | 16 documented paths; machine-readable contract provided |

Test command used from backend: `../../.venv/bin/pytest -q` in the task-specific virtual environment. The exported requirements.lock records installed packages. The unit suite emits a third-party Starlette/httpx deprecation warning.

The standalone schema command was `PYTHONPATH=. python scripts/verify_schema_standalone.py /path/to/postgresql/bin`. The helper emits the same migration DDL through SQLAlchemy's PostgreSQL compiler, then executes it in PostgreSQL single-user mode. This does **not** execute Alembic's online migration bookkeeping. Single-user PostgreSQL implicitly grants superuser powers; it cannot establish that RLS will deny cross-tenant access. PostgreSQL 17 Compose execution remains to be verified.

## Implemented but not executed here

Five API/database integration scenarios in `tests/test_integration.py`:

1. Two independent tenants, cross-tenant API denial, raw-SQL read/write RLS denial, and pooled context reset.
2. Cashier permission restrictions and access revocation with existing tokens.
3. Concurrent retry-safe tenant onboarding and conflicting idempotency payload.
4. Refresh-token reuse and family-wide access-token revocation.
5. Platform metadata access, denial of tenant-data access without membership, suspension enforcement and non-admin platform denial.

The runtime prevents socket creation; normal PostgreSQL/API servers cannot be started here. Docker is also unavailable. Full Compose startup, online migrations, Redis integration, HTTP/browser workflows and CI were **not run**. The source contains the reproducible Compose/CI test path; no external test success is implied.

Run in an isolated development environment:

```bash
docker compose --profile test run --rm tests
```

For release readiness, add and run tests for connection reuse after exceptions, membership/warehouse composite references at raw SQL level, all authorization matrix cases, auth abuse/CSRF against a real browser, and backup restoration. Add financial tests only with the real billing/POS implementations.

## Explicitly not implemented or tested in this milestone

Subscription expiration/entitlements, payment signatures and duplicate webhooks, concurrent POS checkout, financial reconciliation, email/phone verification, password reset, MFA, S3, Celery, production monitoring, backup/restore and production deployment.

## GitHub import startup corrections

Added a repeatable `scripts/setup_env.py` that fills missing secrets while preserving existing values (three tests passed). Replaced the host bind-mounted database initialization script with a PostgreSQL image that copies the script as mode 0644. Role creation now skips an existing role without rotating its password. Added recovery commands for a partially initialized database and LF normalization.

Backend unit tests rerun: 12 passed, 5 database scenarios skipped. The revised Docker startup still requires validation on a Docker host; no local full-stack success is claimed.
