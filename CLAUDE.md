# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI + PostgreSQL backend scaffold, structured as a modular monolith. It runs as one service
today but is layered so `auth` and `users` could be extracted into separate services later without
a rewrite (no cross-module DB access, no shared mutable state, all business logic behind
services/repositories). See `README.md` for the full write-up (architecture rationale, auth/RBAC
flows, middleware ordering, API reference, curl examples).

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt      # includes requirements.txt
cp .env.example .env

# Database (run once against the app_test DB before first test run)
createdb app_test
alembic upgrade head

# Run
uvicorn app.main:app --reload

# Test
pytest                                    # full suite (57 tests), needs POSTGRES_DB=app_test reachable
pytest tests/test_auth.py                 # one file
pytest tests/test_auth.py::test_login_success   # one test
pytest -k "refresh"                       # by keyword

# Lint / format
ruff check .
ruff check . --fix
ruff format .
ruff format --check .

# Migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic history
alembic current
alembic check                             # fails if models and migrations have drifted

# Admin bootstrap (production-safe, idempotent, rejects duplicates)
python -m app.scripts.create_admin --email admin@example.com --username admin --password "S3curePass1"

# Dev-only seed users (refuses to run when ENVIRONMENT=production)
python -m app.scripts.seed_users

# Docker
docker compose up --build
```

Tests target a **dedicated** `app_test` database (never the dev DB) — `tests/conftest.py` sets
`ENVIRONMENT=testing`/`POSTGRES_DB=app_test`/etc. via `os.environ` *before* importing any `app.*`
module, since `app.core.config.settings` is instantiated once at import time. It applies migrations
once per test session (a **synchronous** fixture — Alembic's `env.py` drives its own `asyncio.run()`
internally, so wrapping it in an async fixture would tie the migration connection to one test's
event loop and break under pytest-asyncio's per-function loops) and truncates all tables after every
test for isolation. Override the test DB name with `TEST_POSTGRES_DB`.

## Architecture

Strict one-way layering, enforced by convention (no framework forces it):

```
routes → services → repositories → models
   ↓         ↓
schemas   core (config/security/logging/exceptions)
```

- **`api/routes/*`** — HTTP only: parse request, call one service method, map the result to a
  response schema. No DB queries, no business logic, no auth decisions here.
- **`api/dependencies/*`** — the *only* place auth/RBAC decisions are made (never in middleware).
  `auth.py` has `get_current_user` → `get_current_active_user` → `require_role(*roles)`, layered
  dependencies each adding one check (valid token → active account → role membership).
- **`services/*`** — business logic and **transaction boundaries**. Each public method owns its
  `commit()`/rollback; repositories never commit. E.g. `AuthService.refresh()` revokes the used
  refresh token and issues a new pair as one unit; `UserService.change_password` also revokes all
  of that user's refresh tokens (forces re-login everywhere on password change).
- **`repositories/*`** — one class per entity, plain SQLAlchemy 2.x `select()` queries. Deliberately
  *not* a generic base-repository framework — each repo is hand-written and small.
- **`models/*`** — SQLAlchemy declarative models only. `models/base.py` defines the naming
  convention for constraints/indexes (so Alembic autogenerate produces stable names) and a
  `TimestampMixin`. `app/db/base.py` re-exports `Base` after importing `app.models` (which imports
  every model) — this is what makes Alembic autogeneration see the full schema; if you add a model
  and it's not appearing in `alembic revision --autogenerate`, check it's imported in
  `app/models/__init__.py`.
- **`schemas/*`** — Pydantic v2 request/response models. Never reuse a SQLAlchemy model as a
  response model directly (e.g. `User` the ORM model is never returned from a route — always mapped
  through `UserResponse.model_validate(...)`).
- **`core/*`** — config (`Settings`, env-driven, fails startup if production config is insecure —
  see `_validate_production_safety`), `security.py` (JWT encode/decode + Argon2 hashing, no FastAPI
  imports so it's reusable outside the web layer), `logging.py` (contextvar-based correlation ID +
  JSON formatter), `exceptions.py` (`AppError` subclasses services/repos raise instead of
  `HTTPException`), `error_handlers.py` (translates those into the JSON error envelope).
- **`middleware/*`** — cross-cutting HTTP concerns only (correlation ID, request logging, timing,
  security headers, request-size limiting). Explicitly must never contain auth/RBAC/DB logic.

### Middleware ordering (in `app/main.py`)

Starlette wraps middleware in reverse registration order — the *last* `add_middleware()` call
becomes the *outermost* layer. `main.py` therefore registers them **innermost-first**, with a
comment block explaining why, so the effective per-request order (outer → inner) is:

```
TrustedHost → CORS → SecurityHeaders → RequestSizeLimit → GZip
  → CorrelationId → RequestLogging → ProcessTime → route handler
```

CorrelationId must precede RequestLogging (so logs can include the ID); ProcessTime must be
innermost (so its timer measures only actual app work). Read the comment in `main.py` before
reordering middleware.

### Auth / RBAC

- Access tokens are short-lived JWTs (`ACCESS_TOKEN_EXPIRE_MINUTES`), stateless, not individually
  revocable.
- Refresh tokens are JWTs too, but the server never trusts the JWT alone: each has a `jti` mapping
  to a `refresh_tokens` row storing only a **SHA-256 hash** of the raw token (never the raw token),
  `expires_at`, and nullable `revoked_at`. `/auth/refresh` is single-use rotation: decode → look up
  by `jti` → verify hash → reject if revoked/expired → **revoke the used row** → issue a new pair.
  Replaying an already-rotated token is rejected (theft/replay detection).
- Roles are a fixed `UserRole` enum (`USER`, `ADMIN`) backed by a native Postgres enum type. Add a
  new role by extending the enum + a migration; every `require_role(...)` call site keeps working.

### Error responses

All errors funnel through `app/core/error_handlers.py` into one envelope:
`{"error": {"code", "message", "details", "correlation_id"}}`. Raise an `AppError` subclass
(`NotFoundError`, `ConflictError`, `AuthenticationError`, `AuthorizationError`, `InvalidStateError`)
from a service — never raise `HTTPException` from services, and never let a raw exception with
internal detail (SQL, stack trace, file paths) reach a response body.

## Known environment gotcha

The Alembic-migration-inside-async-fixture issue above (`tests/conftest.py::_apply_migrations`) is
the one non-obvious pytest-asyncio interaction in this codebase — if a future change moves migration
application into an async fixture, expect `RuntimeError: ... attached to a different loop` failures.
