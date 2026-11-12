# SmartRetail Cloud · Milestones 1–2

An executable SaaS foundation using FastAPI, SQLAlchemy, PostgreSQL and React/TypeScript. Includes tenant creation, membership RBAC, branches, warehouse creation, audit records, refresh rotation, and metadata-only platform administration.

**Development foundation, not a production-ready commercial release.** The full brief is staged across five milestones. Subscription plans, trials, entitlements, provider reconciliation and the billing workspace are implemented. Billing defaults to a local sandbox; Razorpay requires your configuration and merchant acceptance tests. POS and retail operations remain Milestone 3 work. Review `docs/TEST_STATUS.md` before treating isolation as verified.

See **[Milestone 2 setup and billing guide](docs/MILESTONE_2.md)** for sandbox testing, Razorpay configuration, background jobs and recovery.

## Start locally

Requires Docker Engine with Docker Compose v2. Run from this directory:

```bash
python3 scripts/setup_env.py
docker compose up --build -d
```

Open **http://localhost:8080**. Register an account, create a workspace, and select it in the sidebar. Your initial Main branch is created transactionally. API documentation is at **http://localhost:8080/docs**; the machine-readable contract is `/openapi.json` and `docs/openapi.json`.

The API runs with a restricted PostgreSQL role; migrations run with separate credentials. PostgreSQL and Redis have no published host ports. The web port is bound to localhost. The initialization script is copied into the PostgreSQL image with mode 0644 to avoid host-mounted script execution permission errors. It only runs automatically on a new database volume. Changing a password in `.env` does not rotate an existing database login.

If a previous startup failed while running `10-app-role.sh`, recover without deleting your database:

```bash
python3 scripts/setup_env.py
docker compose up --build -d --wait db
docker compose exec db bash /docker-entrypoint-initdb.d/10-app-role.sh
docker compose up --build -d
```

The role script is retry-safe and does not change the password of an existing role. Preserve the original database passwords when recovering an initialized database. The environment setup script only generates missing or empty values; if you lost an existing database password, restore it instead of generating a replacement.

For explicit development sample accounts:

```bash
docker compose exec -e DEMO_PASSWORD='Choose-a-local-demo-password-123' api python -m app.seed
```

This adds `owner1@example.com` (Lotus Retail), `owner2@example.com` (Harbor Market), and `platform@example.com`. Their password is the value you supply. No account is seeded automatically. The platform account has no membership in either business.

To add a team member, register their separate account first, then use Team as the business owner. Invitations by email and ownership transfer are not in this slice. The currently supported roles are owner, manager, and cashier.

## Verify

```bash
# Integration and unit tests against the migrated Compose database.
# Use an isolated checkout/Compose project: tests leave generated test records.
docker compose --profile test run --rm tests

# Inspect services and migration outcomes.
docker compose ps -a
docker compose logs migrate api

# Stop services while preserving data.
docker compose down
```

Do not use `down -v` on business data: it deletes database volumes. CI uses a disposable database and removes its own volumes after the job.

Without Docker, install `backend/requirements.lock` in a Python 3.12 virtual environment. Provision PostgreSQL and Redis, create a `smartretail_app` role with `NOSUPERUSER NOBYPASSRLS`, and export `MIGRATION_DATABASE_URL`, `DATABASE_URL`, `JWT_SECRET`, `REDIS_URL`, `SECURE_COOKIES=false`, and `WEB_ORIGIN=http://localhost:5173`. Run `alembic upgrade head` from `backend`, then `uvicorn app.main:app --port 8000`. In `frontend`, run `npm ci` and `npm run dev`. Vite proxies `/api` to port 8000. Use URL-encoded credentials in manually assembled connection strings.

## What's here

- Subscription engine setup: `docs/MILESTONE_2.md`
- Architecture and database design: `docs/ARCHITECTURE.md`
- API examples and contracts: `docs/API.md` and `docs/openapi.json`
- Files and module boundaries: `docs/STRUCTURE.md`
- Phased plan and milestone status: `docs/ROADMAP.md`
- Tests actually run and outstanding validation: `docs/TEST_STATUS.md`
- PostgreSQL integration tests: `backend/tests/test_integration.py`
- Development environment: `compose.yaml`

## Before production

Implement and test identity verification, password reset, optional MFA, durable email delivery, account abuse prevention, merchant billing acceptance tests, tenant-scoped invitations and branch assignments. Resolve every unrun integration check. Deploy behind HTTPS with `SECURE_COOKIES=true` and the exact public `WEB_ORIGIN`; implement trusted-proxy client IP handling (the development API currently rate-limits by direct peer IP, shared behind Nginx). Define secure secret rotation, backups and tested restore drills, retention, monitoring, and deployment rollback. Add dependency vulnerability scanning and a security review.

A Sites static/Worker deployment cannot host the requested Python/PostgreSQL stack. This handoff is a Docker application source package; it has not been deployed to a hosting service.
