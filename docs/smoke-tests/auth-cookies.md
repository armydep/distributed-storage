# Smoke Test: Cookie-based authentication

| | |
|---|---|
| Covers | `docs/design/auth-cookies.md` |
| Implementation commit | `7a7f98d` — Implement cookie-based auth per docs/design/auth-cookies.md |
| Type | Manual, curl-based — run once after any change touching auth, cookies, or CORS |
| Automated equivalent | `pytest tests/test_auth_cookies.py tests/test_auth.py` |

## What this step solves

Until this change, the API only authenticated over the `Authorization: Bearer <token>` header.
That's fine for scripts and future non-browser clients, but it's unusable for the browser SPA
without either storing tokens in JavaScript-reachable storage (an XSS exfiltration risk the
project explicitly rejected — ADR-0012) or hand-rolling a session mechanism from scratch.

This step adds httpOnly cookies as a **second, optional transport** for the exact same JWTs the
API already issues — no new token format, no new revocation model. A client opts in per login
(`use_cookies=true`); everything else (short-lived access tokens, single-use rotating refresh
tokens, server-side revocation, replay detection) behaves identically underneath. Because cookies
attach to requests automatically (including ones a malicious cross-site page can trigger), this
step also adds CSRF protection: state-changing requests authenticated via cookie must carry a
custom `X-CSRF-Protection: 1` header, which a cross-origin page cannot attach without failing the
API's CORS check.

**In plain terms, this smoke test proves:** a browser-style client can log in and get a working
session carried entirely in cookies, JavaScript never needs to see a token, forged cross-site
requests are rejected, and none of this affects existing bearer/API clients (curl, scripts, the
future sync client) even a little.

## Prerequisites

- The app running locally: `uvicorn app.main:app --reload` (or against the Docker Compose stack).
- A reachable PostgreSQL with migrations applied (`alembic upgrade head`).
- `curl` and `python3` on the machine running the test.

Commands below assume `BASE=http://localhost:8000/api/v1`. Adjust the host/port if different.

## Procedure

### 1. Register a test user

```bash
BASE=http://localhost:8000/api/v1
curl -s -X POST "$BASE/auth/register" -H "Content-Type: application/json" \
  -d '{"email":"smoke@example.com","username":"smokeuser","password":"SmokePass1"}'
```
**Expect:** `201`-shaped JSON body with the new user's `id`, `email`, `username` — no `password` or
`hashed_password` field anywhere in the response.

### 2. Cookie login without the CSRF header — must be rejected

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$BASE/auth/login" \
  -d "username=smokeuser&password=SmokePass1&use_cookies=true"
```
**Expect:** `HTTP 403`, body `error.code == "CSRF_HEADER_MISSING"`.

This is the login-CSRF fix found during implementation planning: cookie-mode login has no prior
credential for the general CSRF rule to key off, so it's checked directly against the
`use_cookies` flag instead. If this step ever returns `200`, that protection has regressed.

### 3. Cookie login with the CSRF header — sets both cookies

```bash
curl -s -c /tmp/smoke_cookies.txt -D /tmp/smoke_headers.txt -o /tmp/smoke_login.json \
  -w "HTTP %{http_code}\n" -X POST "$BASE/auth/login" \
  -H "X-CSRF-Protection: 1" \
  -d "username=smokeuser&password=SmokePass1&use_cookies=true"
cat /tmp/smoke_login.json
grep -i "^set-cookie" /tmp/smoke_headers.txt
```
**Expect:**
- `HTTP 200`.
- Body has `user` (matching the registered user) and `expires_in` (> 0) — **no** `access_token` or
  `refresh_token` key anywhere. This is the entire point: the SPA's JavaScript never sees a token.
- Two `Set-Cookie` headers:
  - `ds_access=...; HttpOnly; Max-Age=900; Path=/api/v1; SameSite=none; Secure`
  - `ds_refresh=...; HttpOnly; Max-Age=2592000; Path=/api/v1/auth; SameSite=none; Secure`

  (`Max-Age` values reflect the default 15 min / 30 day lifetimes — adjust if `.env` overrides
  `ACCESS_TOKEN_EXPIRE_MINUTES`/`REFRESH_TOKEN_EXPIRE_DAYS`.) The refresh cookie's `Path` must be
  `/api/v1/auth`, not `/api/v1/auth/refresh` — narrower would silently break step 6 below (this
  was the other defect found during planning).

### 4. Cookie-authenticated read — no CSRF header needed

```bash
curl -s -b /tmp/smoke_cookies.txt -o /dev/null -w "HTTP %{http_code}\n" "$BASE/users/me"
```
**Expect:** `HTTP 200`. Safe methods never require the CSRF header, cookie or not.

### 5. Cookie-authenticated mutation — CSRF header enforced

```bash
echo "--- without header (expect 403) ---"
curl -s -b /tmp/smoke_cookies.txt -o /dev/null -w "HTTP %{http_code}\n" -X POST "$BASE/auth/logout"

echo "--- with header (expect 204) ---"
curl -s -b /tmp/smoke_cookies.txt -c /tmp/smoke_cookies2.txt -D /tmp/smoke_headers2.txt \
  -o /dev/null -w "HTTP %{http_code}\n" -X POST "$BASE/auth/logout" -H "X-CSRF-Protection: 1"
grep -i "^set-cookie" /tmp/smoke_headers2.txt
```
**Expect:**
- Without the header: `HTTP 403`, `CSRF_HEADER_MISSING`.
- With the header: `HTTP 204`, and both `Set-Cookie` headers show `Max-Age=0` with their original
  `Path` values — confirming the cookies are actually cleared (a mismatched `Path` on the clearing
  call is a silent no-op that leaves stale cookies behind, a specific failure mode called out in
  the implementation plan).

### 6. Confirm logout actually revoked the session

```bash
curl -s -b /tmp/smoke_cookies.txt -o /dev/null -w "HTTP %{http_code}\n" -X POST "$BASE/auth/refresh" \
  -H "X-CSRF-Protection: 1"
```
**Expect:** `HTTP 401`. (Using the original, now-logged-out `smoke_cookies.txt` on purpose — after
step 5's `Set-Cookie: Max-Age=0` responses, a real browser would have dropped these cookies
already; this step exercises server-side revocation directly regardless of client-side cleanup.)

### 7. Existing bearer flow — completely unaffected

```bash
curl -s -X POST "$BASE/auth/login" -d "username=smokeuser&password=SmokePass1" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('access_token present:', bool(d.get('access_token'))); print('refresh_token present:', bool(d.get('refresh_token')))"
```
**Expect:** both `True`. Omitting `use_cookies` must behave byte-identically to before this change
— no cookies set, tokens in the body as always.

### Cleanup

```bash
rm -f /tmp/smoke_cookies.txt /tmp/smoke_cookies2.txt /tmp/smoke_headers.txt /tmp/smoke_headers2.txt \
      /tmp/smoke_login.json
```

## Pass criteria

All seven steps match their "Expect" exactly. Any deviation — especially step 2 returning `200`,
step 3's refresh cookie `Path` being `/api/v1/auth/refresh`, or step 7 gaining cookies it shouldn't
— indicates a regression in this feature and should block merging further work on top of it.
