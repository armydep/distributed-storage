# distributed-storage

A production-oriented REST API backend scaffold built with **FastAPI** and **PostgreSQL**. It runs
today as a single modular monolith, but its layering keeps modules loosely coupled so pieces
(authentication, user management, ...) can be extracted into independent services later without a
rewrite.

## Technology stack

- Python 3.12+
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x (async ORM, `asyncpg` driver)
- Alembic (async-aware migrations)
- Pydantic v2 / Pydantic Settings
- JWT auth via the OAuth2 password (bearer-token) flow
- Argon2id password hashing (`argon2-cffi`)
- Pytest + httpx (async tests against a real PostgreSQL database)
- Ruff (lint, import sort, format)
- Docker / Docker Compose

## Architecture

Layered, modular monolith. Each layer has one job and only talks to the layer directly below it:

```
app/
├── api/
│   ├── dependencies/   # auth, RBAC, DB session, pagination — FastAPI Depends()
│   └── routes/         # HTTP request/response mapping only
├── core/                # config, security, logging, exceptions, error handlers
├── db/                  # async engine, session factory, Base metadata
├── middleware/           # cross-cutting HTTP concerns (correlation ID, logging, ...)
├── models/               # SQLAlchemy declarative models (persistence)
├── repositories/         # database access (SELECT/INSERT/UPDATE/DELETE only)
├── schemas/              # Pydantic request/response models
├── services/             # business logic + transaction boundaries
├── scripts/              # one-off admin CLI scripts
└── main.py               # FastAPI app wiring: middleware, routers, lifespan
```

**Responsibility boundaries** (strictly enforced, no shortcuts):

| Layer | Responsibility | Never does |
|---|---|---|
| `api/routes` | Parse request, call a service, map result to a response schema | Business logic, DB queries, auth decisions |
| `api/dependencies` | Authentication, RBAC, DB session injection, pagination parsing | Business logic |
| `services` | Business rules, transaction boundaries (`commit`/`rollback`) | Raw SQL/ORM queries, HTTP concerns |
| `repositories` | SQLAlchemy queries for one entity | Committing transactions, business rules |
| `models` | Persistence schema (SQLAlchemy) | Validation, serialization |
| `schemas` | Request validation / response serialization (Pydantic) | Persistence, business logic |
| `core` | Config, JWT/password primitives, logging, exception types | HTTP, DB |
| `middleware` | Cross-cutting HTTP concerns (IDs, headers, timing, size limits) | Auth decisions, business logic, DB |

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt

cp .env.example .env                  # edit POSTGRES_* / JWT_SECRET_KEY if needed

alembic upgrade head
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`, docs at `http://localhost:8000/api/v1/docs`.

### Database configuration

PostgreSQL connection settings are environment variables (`POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`), assembled into an async `postgresql+asyncpg://`
URL. Set `DATABASE_URL` directly to override the assembled URL entirely (e.g. for managed DB
providers). See `.env.example` for the full list of variables, including JWT, CORS, trusted hosts,
and request-size limits.

Tables are **never** created automatically at startup — only Alembic migrations create schema.

### Alembic migrations

`alembic/env.py` uses an async SQLAlchemy engine and reads its target metadata from
`app.db.base.Base` (which imports every model), so autogeneration always reflects the current
models.

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic history
alembic current
```

These commands work identically locally and inside the `api` container (`docker compose exec api alembic ...`).

### Running tests

Tests run against a **dedicated** PostgreSQL database (`POSTGRES_DB=app_test` by default) — never
your development database. `tests/conftest.py` sets environment variables before importing the app,
applies migrations once per test session, and truncates all tables after every test so tests are
independent and repeatable.

```bash
createdb app_test   # once, if it doesn't already exist
pytest
```

Override the test database name with `TEST_POSTGRES_DB` if needed.

### Ruff

```bash
ruff check .
ruff check . --fix
ruff format .
ruff format --check .
```

### Creating the first administrator

```bash
python -m app.scripts.create_admin \
    --email admin@example.com --username admin --password "S3curePass1"
```

Credentials can also come from `ADMIN_EMAIL` / `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment
variables (avoids shell history). The script reuses the same `UserCreate` validation and Argon2
hashing the application uses everywhere else, and refuses to create a duplicate. Inside Docker
Compose:

```bash
docker compose exec api python -m app.scripts.create_admin \
    --email admin@example.com --username admin --password "S3curePass1"
```

## Docker setup

```bash
docker compose up --build
```

This starts:
- `db` — PostgreSQL 16 with a persistent named volume and a healthcheck.
- `api` — waits for `db` to report healthy, applies `alembic upgrade head`, then starts
  `uvicorn app.main:app --host 0.0.0.0 --port 8000` (see `docker/entrypoint.sh`). Runs as a
  non-root user in the container.

Configuration is passed via environment variables (see `docker-compose.yml`); override them with a
`.env` file in the project root or your shell environment. No production secrets are hardcoded in
any Docker file — the compose defaults are development-only placeholders.

For development, Compose also seeds one account for each role after migrations:

| Role | Username | Password |
|---|---|---|
| User | `user` | `UserPass123` |
| Admin | `admin` | `AdminPass123` |

The seed is idempotent and refuses to run when `ENVIRONMENT=production`. Override the credentials
with the `SEED_USER_*` / `SEED_ADMIN_*` variables in `.env`, or set `SEED_DEMO_USERS=false` to
disable it. Run it manually with `python -m app.scripts.seed_users`.

## Authentication flow

1. `POST /api/v1/auth/register` — creates a user (`USER` role by default), Argon2-hashes the
   password. Returns the user (never the password/hash).
2. `POST /api/v1/auth/login` — OAuth2 password flow (`OAuth2PasswordRequestForm`: form-encoded
   `username` + `password`; `username` may be either the username or the email). Verifies the
   password, checks `is_active`, and returns an access/refresh token pair.
3. Protected endpoints require `Authorization: Bearer <access_token>`. The
   `get_current_active_user` dependency decodes the JWT, loads the user, and rejects missing,
   invalid, expired, or inactive-account tokens with a 401/403.
4. `POST /api/v1/auth/refresh` — exchanges a valid, non-revoked, non-expired refresh token for a
   **new** access/refresh pair, and **revokes the old refresh token** (rotation). Reusing an
   already-rotated (or revoked) refresh token is rejected — this detects token theft/replay.
5. `POST /api/v1/auth/logout` — requires a valid access token *and* the refresh token to revoke;
   marks that refresh token revoked in the database.

### Refresh-token lifecycle

- Refresh tokens are JWTs like access tokens, but the server never trusts the JWT alone: each one
  has a `jti` (UUID) that maps to a `refresh_tokens` row storing only a **SHA-256 hash** of the raw
  token (never the raw token itself), its `expires_at`, and a nullable `revoked_at`.
- On `/auth/refresh`: decode → look up by `jti` → compare hash → reject if revoked or expired →
  **revoke the used token** → issue a brand-new pair. This means every refresh token is single-use;
  a stolen-and-reused token is detected on its second use.
- On password change or account deactivation, **all** of a user's refresh tokens are revoked
  server-side, immediately invalidating any other active sessions.
- Access tokens are short-lived (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 15) and are **not**
  individually revocable by design (stateless); refresh tokens are long-lived
  (`REFRESH_TOKEN_EXPIRE_DAYS`, default 30) and fully revocable, which is the standard tradeoff for
  this pattern.

### Roles and RBAC

Two fixed roles: `UserRole.USER` and `UserRole.ADMIN` (a Python enum backed by a Postgres native
enum type). RBAC is implemented **entirely as FastAPI dependencies** (`app/api/dependencies/auth.py`),
never in middleware:

```python
async def get_current_user(...) -> User: ...          # valid access token required
async def get_current_active_user(...) -> User: ...   # + is_active required
def require_role(*roles: UserRole):                    # + role membership required
    async def _require_role(current_user: CurrentUser) -> User: ...
    return _require_role
```

```python
@router.get("/admin-only")
async def admin_only(current_user: User = Depends(require_role(UserRole.ADMIN))):
    ...
```

Adding a third role later is a one-line enum change; every `require_role(...)` call site keeps
working unchanged.

## Middleware

Custom middleware lives in `app/middleware/` — each file is one cross-cutting concern, and none of
them touch authentication, RBAC, or the database:

```
app/middleware/
├── correlation_id.py    # accepts/generates X-Correlation-ID
├── logging.py            # one structured log line per request
├── process_time.py       # X-Process-Time-Ms header
├── security_headers.py   # X-Content-Type-Options, X-Frame-Options, CSP, ...
└── request_size.py       # rejects oversized bodies with 413
```

Plus Starlette's built-in `CORSMiddleware`, `TrustedHostMiddleware`, and `GZipMiddleware`.

### Registration order and why it matters

Starlette wraps middleware in the **reverse** order `add_middleware()` is called — the *last*
one added becomes the *outermost* layer, running first on the way in and last on the way out.
`app/main.py` adds them innermost-first so the effective **request execution order** (outer → inner)
reads:

```
TrustedHost → CORS → SecurityHeaders → RequestSizeLimit → GZip
  → CorrelationId → RequestLogging → ProcessTime → route handler
```

- **TrustedHost** is outermost: reject a forged `Host` header before any other work happens.
- **CORS** sits next so CORS headers are applied consistently, including on error responses
  produced further in.
- **SecurityHeaders** wraps almost everything so *every* response — including errors — carries the
  hardening headers.
- **RequestSizeLimit** runs before the body would otherwise be read/buffered.
- **GZip** compresses the final response body.
- **CorrelationId** must run before **RequestLogging** so every log line for a request can include
  its correlation ID.
- **ProcessTime** is innermost, so its timer wraps only actual application work (routing +
  dependencies + endpoint), not the other middleware.

### Correlation IDs

Every request gets an `X-Correlation-ID`: a caller-supplied header is reused if it's a valid UUID,
otherwise one is generated. It's stored in a `contextvar` (so any logger anywhere in the request can
include it), attached to `request.state`, and always echoed back in the response header.

### Error responses

All errors — validation, auth, not-found, conflict, database, or truly unexpected — are translated
by `app/core/error_handlers.py` into one consistent envelope:

```json
{
  "error": {
    "code": "USER_NOT_FOUND",
    "message": "The requested user was not found",
    "details": null,
    "correlation_id": "b3b4a6b0-4e21-4a8b-9a13-2f9a6b9d6a11"
  }
}
```

No stack traces, SQL, token values, password data, or internal file paths ever reach the client.
Unexpected exceptions are logged server-side with full context and returned as a generic
`500 INTERNAL_SERVER_ERROR`.

## Database and transaction strategy

- One process-wide async engine (`app/db/session.py`), connection-pooled, `pool_pre_ping=True`.
- **No global session** — `get_db()` is a FastAPI dependency that yields one `AsyncSession` per
  request and rolls it back on any exception.
- Repositories only issue queries; they never call `commit()`.
- Services own transaction boundaries: each public service method commits once, at the point where
  its unit of work is logically complete (e.g. `AuthService.register`, `UserService.change_password`).
- `GET /ready` verifies live DB connectivity (`SELECT 1`) and returns `503` if the database is
  unreachable.
- The engine is disposed cleanly during FastAPI's `lifespan` shutdown.

## Main API endpoints

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

GET    /api/v1/users/me
PATCH  /api/v1/users/me
POST   /api/v1/users/me/change-password

GET    /api/v1/users                 (admin; pagination + role/is_active/search filters)
GET    /api/v1/users/{user_id}       (admin)
PATCH  /api/v1/users/{user_id}       (admin)
POST   /api/v1/users/{user_id}/activate    (admin)
POST   /api/v1/users/{user_id}/deactivate  (admin)
DELETE /api/v1/users/{user_id}       (admin)

GET    /health   # liveness
GET    /ready    # readiness (verifies DB connectivity)
```

Interactive docs: `GET /api/v1/docs` (Swagger UI, wired to the OAuth2 password flow — use the
"Authorize" button with your username/password).

### Example requests

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","username":"jane","password":"StrongPass1"}'

# Login (OAuth2 password flow: form-encoded, not JSON)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=jane&password=StrongPass1"

# Refresh
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'

# Current user
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"

# List users (admin)
curl "http://localhost:8000/api/v1/users?page=1&page_size=20&role=user" \
  -H "Authorization: Bearer <admin_access_token>"

# Update a user (admin)
curl -X PATCH http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"role":"admin"}'

# Logout
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

## Important security decisions

- Passwords hashed with **Argon2id** (`argon2-cffi`), never stored or logged in plaintext.
- Refresh tokens stored as a **SHA-256 hash only**; a database leak cannot be replayed as a session.
- Refresh-token **rotation with reuse detection**: every refresh issues a new pair and revokes the
  old one; replaying an old one is rejected.
- JWT secret, DB credentials, and other secrets are environment-driven, never hardcoded; `Settings`
  fails startup in production if `JWT_SECRET_KEY` is short/default, `DEBUG=true`, or
  `CORS_ORIGINS`/`TRUSTED_HOSTS` contain a wildcard.
- CORS is never configured with a wildcard origin *and* credentials simultaneously.
- Middleware never logs `Authorization` headers, cookies, tokens, or request bodies — only method,
  path, status, and duration.
- Admins cannot deactivate, delete, or demote their own account through the API (prevents
  self-lockout).

## Future microservice extraction

The codebase is a modular monolith on purpose: no message broker, service mesh, API gateway, or
distributed transactions have been introduced, because none are needed yet. When/if scale demands
it, two modules are natural extraction points, since they're already isolated behind
repositories/services with no cross-module DB access:

- **Authentication service** — `app/services/auth.py`, `app/models/refresh_token.py`, and the
  `/auth/*` routes. Owns login, tokens, and refresh-token storage.
- **User-management service** — `app/services/user.py`, `app/models/user.py`, and the `/users/*`
  routes. Owns profile data and admin user operations.

Extracting either today would mean: give it its own database/schema, replace in-process service
calls with HTTP (or a message queue, once actually justified) calls from the remaining monolith,
and keep the same request/response contracts. No code today reaches across these boundaries
directly (e.g. no route imports another module's repository), which is what makes this practical
later instead of a rewrite.

## Assumptions

- `/auth/login` uses `OAuth2PasswordRequestForm` (form-encoded `username`/`password`) rather than a
  JSON body, per FastAPI's standard OAuth2-password-flow convention — this is what makes the
  Swagger "Authorize" button work out of the box. A `LoginRequest` JSON schema is still defined in
  `app/schemas/auth.py` for documentation purposes.
- `username` in the login form accepts either the account's username or its email.
- Activate/deactivate are modeled as dedicated `POST /users/{id}/activate|deactivate` endpoints (in
  addition to `PATCH .../{id}` supporting `is_active`), since that reads more clearly as an explicit
  administrative action.
- Readiness failure (`GET /ready` when the DB is unreachable) returns `503 Service Unavailable`,
  the conventional status for that case (not in the task's explicit status-code list, which was
  described as non-exhaustive).
- Local/CI validation used PostgreSQL running directly on the host (`localhost:5432`) rather than
  inside a container, since the sandboxed validation environment's Docker daemon could not pull
  base images (see below) — the schema, migrations, and application code are identical either way.

## Validation performed

Actually executed in this environment, against a real PostgreSQL 16 instance:

- `pip install -r requirements-dev.txt` — clean install.
- `python -c "from app.main import app"` — application imports and builds its route table.
- `alembic upgrade head` / `alembic downgrade -1` / `alembic upgrade head` again / `alembic history`
  / `alembic current` — full migration round-trip, including a Postgres native enum type created
  and dropped cleanly (this caught and fixed a real bug: autogenerate's default `drop_table`
  downgrade doesn't drop the associated enum type, causing a "type already exists" error on
  re-upgrade — fixed by managing the enum explicitly in the migration).
- `alembic check` — model metadata matches the migration exactly (no drift).
- `pytest` — **57/57 tests passed**, twice in a row (repeatability check), covering registration,
  login, access/refresh token validation (valid/expired/invalid/missing), refresh rotation +
  reuse/revocation detection, logout, current-user profile/password endpoints, RBAC (admin-only,
  inactive-user denial, self-service protections), user CRUD + pagination + filtering, and every
  middleware behavior (correlation IDs, security headers, CORS, trusted host, request-size 413,
  consistent 500 envelope, no secrets in logs).
- `ruff check .` and `ruff format --check .` — clean.
- `python -m app.scripts.create_admin` — creates an administrator, rejects a duplicate with exit
  code 1, hashes the password with the same Argon2 path the app uses.
- `docker compose config` — Dockerfile/compose files parse and resolve correctly, including `.env`
  interpolation.

## Remaining limitations

- **`docker compose up --build` could not be fully executed in this sandboxed validation
  environment**: its Docker daemon's image pulls from Docker Hub are blocked by the sandbox's
  outbound network policy (a `403` on the CDN backing `docker.io`), unrelated to this project's
  configuration. The `Dockerfile`, `docker-compose.yml`, and `docker/entrypoint.sh` were reviewed
  manually and validated structurally (`docker compose config`, `sh -n entrypoint.sh`); they follow
  the same patterns (multi-stage-free slim base, non-root user, healthchecks, wait-for-DB +
  migrate-then-serve entrypoint) as the rest of the stack that *was* fully exercised. Please run
  `docker compose up --build` in a normal environment with Docker Hub access to do a final check.
- No integration test exercises the Docker image itself (only the application code directly).
- Rate limiting / brute-force login throttling is not implemented — out of scope for this scaffold,
  but worth adding (e.g. via a reverse proxy or a dedicated dependency) before internet-facing
  production use.
