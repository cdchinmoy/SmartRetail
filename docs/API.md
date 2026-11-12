# Milestones 1–2 API contract

Canonical machine-readable contract: `openapi.json` in this folder, generated from the application. Prefix `/api/v1`. UUIDs are strings. Exact request/response schemas, validation and required headers are in OpenAPI. Paths have no trailing slash.

| Method | Path | Access / behavior |
|---|---|---|
| POST | /auth/register | email/password; 201 + access token; refresh cookie |
| POST | /auth/login | email/password; 200 + access token; refresh cookie |
| POST | /auth/refresh | refresh cookie + exact Origin; rotate token; 401 on replay |
| POST | /auth/logout | Bearer + exact Origin; revoke all user sessions |
| GET | /auth/me | Bearer; user ID/email/platform flag |
| GET | /tenants | Bearer; own active memberships, including suspended businesses |
| POST | /tenants | Bearer + UUID Idempotency-Key; body name; 201 |
| GET | /branches | Tenant + branches.read; offset >=0, limit 1–100 |
| POST | /branches | Tenant + branches.write; body name; 201 |
| GET | /branches/{branch_id} | Tenant + branches.read; cross-tenant ID returns 404 |
| POST | /warehouses | Tenant + branches.write; name/branch_id; 201 |
| GET | /members | Tenant + members.manage; member list |
| POST | /members | Tenant + members.manage; registered email + manager/cashier role; 201 |
| DELETE | /members/{member_id} | Tenant + members.manage; revoke; 204; cannot revoke owner |
| GET | /audit | Tenant + audit.read; limit 1–100; latest first |
| GET | /platform/overview | Platform admin only; counts by operational tenant status |
| GET | /platform/tenants | Platform admin only; offset/limit; metadata only |
| PATCH | /platform/tenants/{tenant_id} | Platform admin only; status active/suspended; audit |

Tenant access requires `Authorization: Bearer <access_token>` **and** `X-Tenant-ID: <verified-member-business-uuid>`. Platform admin alone cannot use these operations.

Registration/login body:

```json
{"email":"owner@example.com","password":"Choose-a-long-unique-password"}
```

Tenant creation request:

```http
POST /api/v1/tenants
Authorization: Bearer <access_token>
Idempotency-Key: <client-generated-uuid>
Content-Type: application/json

{"name":"Lotus Retail"}
```

Tenant creation response:

```json
{"id":"<tenant-uuid>","name":"Lotus Retail","status":"active"}
```

Error envelope:

```json
{"error":{"code":"HTTP_403","message":"Business access denied"},"request_id":"<request-uuid>"}
```

422 validation errors omit submitted input, avoiding password echo. 409 indicates a uniqueness/relationship conflict or changed idempotency payload. 429 is the auth rate limit. 503 means Redis-backed auth throttling is unavailable; login/register/refresh fail closed. A new server-generated request ID appears in every normal response header.

The frontend keeps access tokens in memory and calls refresh on reload. Refresh cookies are HttpOnly, SameSite=Strict, scoped to `/api/v1/auth`, and Secure by default. Local Compose explicitly opts out of Secure for localhost HTTP. Mutation requests use JSON; no CORS is configured because frontend/API share an origin. Cross-origin hosting needs a deliberate cookie/CORS/CSRF redesign.

Lists of branches and platform tenants support offset/limit. Audit supports bounded latest entries. Membership and own-tenant lists are not yet paginated; add pagination before supporting very large enterprise accounts. Filtering beyond the implemented parameters is a later API enhancement. Branch writes and member creation have uniqueness constraints but do not yet provide general idempotency-key replay semantics; only tenant onboarding does.

## Subscription API additions

All tenant billing routes require owner billing permission and `X-Tenant-ID`. Mutating commands require UUID `Idempotency-Key`, return 202 plus an operation ID, and are executed by the worker. Do not interpret 202 as paid or completed.

| Method | Path | Purpose |
|---|---|---|
| GET | /subscriptions/plans | Public catalog and provider mode |
| GET | /subscriptions/current | Status, periods, limits, usage and notices |
| POST | /billing/checkout | Body: plan code, monthly/yearly cycle |
| POST | /subscriptions/change | Same selection; schedule next-cycle change |
| POST | /subscriptions/cancel | Cancel recurring billing |
| POST | /billing/reconcile | Request provider synchronization |
| POST | /billing/sandbox/charge | Development-only payment simulation |
| POST | /billing/sandbox/fail | Development-only failure simulation |
| GET | /billing/operations | Recent commands and outcomes; bounded limit |
| GET | /billing/invoices | Tenant payment history; offset/limit |
| GET | /billing/invoices/{invoice_id} | Tenant-scoped receipt data |
| POST | /billing/webhooks/{provider} | Signed provider event; no browser auth |
| GET | /platform/billing/plans | Operator catalog including provider IDs |
| POST | /platform/billing/plans | Create a new immutable-price plan version |
| PUT | /platform/billing/plans/{code}/provider | Set initial monthly/yearly Razorpay mappings |
| GET | /platform/billing/overview | SaaS metrics and operations needing attention |
| POST | /platform/billing/tenants/{tenant_id}/operations/{operation_id}/recover | Verify an uncertain provider operation |

402 means billing no longer permits new business records; 409 may indicate a quota, another billing operation or an idempotency conflict. Reads are retained, but normal tenant membership and administrative suspension checks still apply.

The Razorpay webhook requires `X-Razorpay-Signature` and `X-Razorpay-Event-ID`. Sandbox webhooks require `X-Billing-Signature`, `X-Billing-Event-ID` and a separately configured `SANDBOX_WEBHOOK_SECRET`; the UI simulations do not require a webhook secret. See MILESTONE_2.md for replay and recovery behavior.
