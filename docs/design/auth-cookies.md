# Design: Cookie-based authentication for the SPA

| | |
|---|---|
| Status | Approved |
| Feature | SPA login sessions (PRD §5.8 prerequisite) |
| ADRs | [0011 separate origins](../adr/0011-separate-origins-cors.md), [0012 httpOnly cookies](../adr/0012-httponly-cookie-session.md) |
| Depends on | Existing bearer-JWT auth (access + rotating refresh tokens) |
| Last updated | 2026-07-19 (implementation corrections) |

## 1. Goal

Let the React SPA authenticate against the API without its JavaScript ever holding a token,
preserving every existing security property: short-lived access tokens, single-use rotating
refresh tokens, server-side revocation, replay detection. Non-browser clients (curl, scripts,
future sync client) keep the bearer flow exactly as-is.

**Out of scope:** SPA-side implementation structure (own design doc), "remember me" variants,
MFA, third-party login.

## 2. Approach in one paragraph

The existing JWTs stay exactly what they are — the only change is *transport*. Two httpOnly
cookies carry the access and refresh JWTs instead of the response body. CSRF is handled by
requiring a custom request header on mutating cookie-authenticated requests (unforgeable
cross-origin without passing CORS preflight). Session continuity uses refresh-on-401 with a
single retry.

## 3. Cookie contract

| | Access cookie | Refresh cookie |
|---|---|---|
| Name | `ds_access` | `ds_refresh` |
| Value | the existing access JWT | the existing refresh JWT |
| HttpOnly | yes | yes |
| Secure | yes | yes |
| SameSite | `None` (cross-origin SPA → API, per ADR-0011) | `None` |
| Path | `/api/v1` | `/api/v1/auth` |
| Max-Age | access-token lifetime | refresh-token lifetime |
| Domain | unset (host-only) | unset (host-only) |

Notes:

- The refresh cookie's `Path` is scoped to `/api/v1/auth`, not just `/api/v1/auth/refresh` as
  originally specified — a narrower scope would never be sent to `/auth/logout`, which also needs
  to read it (browsers match cookie `Path` as a prefix of the request path, so a request to
  `/auth/logout` does not carry a cookie scoped to `/auth/refresh`). This was caught during
  implementation planning, before any code shipped with the bug. The long-lived credential is
  still excluded from every ordinary resource request — it now rides along (harmlessly, since
  they don't read it) on `/auth/login` and `/auth/register` too, in exchange for actually reaching
  `/auth/logout`.
- `SameSite=None` **requires** `Secure`, which is why any non-localhost deployment needs HTTPS on
  all origins (already a hard requirement in ADR-0011). Local development relies on browsers'
  localhost exemption (Secure cookies are accepted on `http://localhost`).
- Logout and refresh-rotation clear/replace cookies via standard `Set-Cookie` with new values or
  `Max-Age=0`.

## 4. Dual transport rule

Every authenticated endpoint accepts credentials from **either** source, resolved in this order:

1. `Authorization: Bearer <token>` header, if present — existing behavior, unchanged.
2. Otherwise the `ds_access` cookie.

The token inside is validated identically regardless of transport. Bearer clients never see a
behavioral difference.

## 5. CSRF protection (custom-header check)

Because cookies attach automatically, a malicious site could otherwise fire state-changing
requests as a logged-in user. Chosen mechanism (owner decision): **mutating requests
authenticated via cookie must carry the header `X-CSRF-Protection: 1`.**

- Applies to POST/PUT/PATCH/DELETE when the credential came from a cookie. Absent/wrong header →
  `403 FORBIDDEN` with a distinct error code (`CSRF_HEADER_MISSING`).
- Requests authenticated via `Authorization` header are exempt — attaching that header is itself
  impossible for a CSRF attacker (it is never sent automatically).
- Safe methods (GET/HEAD/OPTIONS) are exempt; they must remain side-effect-free (already a
  platform rule).
- Why it works: a cross-origin page cannot attach a custom header without the browser issuing a
  CORS preflight, and the API's allowlist rejects foreign origins. **This makes strict CORS a
  security control, not a convenience** — the allowlist must never be `*`, and this invariant is
  asserted by config validation in production (extending the existing
  `_validate_production_safety`).
- Enforcement lives in the auth dependency chain (the only place auth decisions are made — never
  middleware), triggered when the resolved credential source is a cookie.

**Login is a special case, added during implementation planning.** The rule above triggers on
"credential resolved as a cookie" — but `/auth/login` has no prior credential, so the rule never
fires there by construction, leaving it unprotected. Worse, `/auth/login` is submitted as
`application/x-www-form-urlencoded`, one of the three CORS-safelisted content types: a cross-site
form POST is a "simple request" that reaches the server with no preflight and isn't blocked (CORS
only stops the attacker's JS from *reading* the response, not the request from executing or a
`Set-Cookie` from being stored). Combined with `SameSite=None`, this is a working login-CSRF
primitive — an attacker page can silently log a victim into an account the attacker controls.
**Fix:** `POST /auth/login` with `use_cookies=true` requires the `X-CSRF-Protection: 1` header
too, checked directly against the `use_cookies` flag rather than against a resolved credential
source (there isn't one yet).

## 6. Endpoint changes

| Endpoint | Change |
|---|---|
| `POST /auth/login` | New optional request flag `use_cookies` (default `false`). When set: requires the `X-CSRF-Protection` header (see §5's login special case) and response **sets both cookies** and the body returns the user + access-token expiry — **no raw tokens in the body** (the whole point is that SPA JS never sees them). When unset: exact current behavior. |
| `POST /auth/refresh` | Accepts the refresh token from the `ds_refresh` cookie when no body token is provided. Rotation semantics unchanged (old token revoked, new pair issued); in cookie mode the new pair is set as cookies, body carries expiry only. |
| `POST /auth/logout` | Accepts the refresh token from the cookie; revokes it as today and clears both cookies. Idempotent, as today. |
| `GET /users/me` | Unchanged — doubles as the SPA's session-bootstrap probe on page load. |

No new endpoints. Registration, password change, and all other routes are untouched (they simply
gain the dual-transport + CSRF rules like every authenticated route).

## 7. Flows

**Login:** SPA posts credentials with `use_cookies: true` → API validates (existing service) →
sets both cookies → SPA stores only "I'm logged in" state in memory and fetches `/users/me`.

**Authenticated request:** browser attaches `ds_access` automatically; SPA attaches
`X-CSRF-Protection: 1` on every mutating call (a one-line default in its HTTP client).

**Expiry / refresh-on-401 (owner decision):** any request returning `401` triggers exactly one
silent `POST /auth/refresh` (browser attaches `ds_refresh` automatically), then a retry of the
original request. A second `401` means the session is dead → SPA clears state and shows login.
Concurrent 401s (parallel requests, multiple components) must share **one** in-flight refresh —
single-use rotation makes parallel refresh calls self-defeating: the second one presents an
already-rotated token and gets rejected as replay. The SPA serializes refresh behind a shared
promise; multi-tab overlap that still slips through simply logs that tab out — safe, mildly
annoying, accepted.

**Logout:** SPA posts logout (with CSRF header) → refresh token revoked server-side, cookies
cleared → local state dropped.

**Page reload:** memory state is gone; SPA calls `/users/me` — the cookie either works
(logged in), or the 401→refresh→retry path restores the session, or login is shown. No token
persistence anywhere in JS-accessible storage, ever.

## 8. CORS requirements (production-critical, per §5)

- `allow_origins`: the exact SPA origin(s) — never `*` (already enforced), and now also *required
  to be non-empty and credentialed* for the SPA to function.
- `allow_credentials: true`.
- `allow_headers` must include `X-CSRF-Protection` (and `Content-Type`).
- Preflight responses must stay uncached-correct if origins change (default `max-age` is fine).

## 9. Security considerations

- **XSS residual risk:** httpOnly means script cannot *exfiltrate* tokens, but injected script
  could still call the API in-page. Mitigations: the SPA ships a strict CSP, no third-party
  script injection points, dependency hygiene. This is the accepted trade recorded in ADR-0012.
- **CSRF depends on CORS correctness** — see §5; config validation makes a wildcard-with-cookies
  deployment fail at startup.
- **Refresh cookie exposure surface** is a single path; access cookie lifetime stays short
  (existing default 15 min).
- **No behavior change for bearer clients** — the attack surface added is exactly: cookie
  transport + one header check.

## 10. Test plan (extends the existing auth suite)

- Login with `use_cookies` sets both cookies with the exact attributes of §3 and returns no raw
  tokens in the body; without the flag, behavior is byte-identical to today.
- Cookie-authenticated GET works without the CSRF header; mutating request without the header →
  403 `CSRF_HEADER_MISSING`; with header → succeeds.
- Bearer-authenticated mutating request needs no CSRF header (regression guard).
- Refresh via cookie rotates: old refresh cookie replayed → 401 (existing replay test, cookie
  transport).
- Logout clears cookies and revokes; subsequent cookie refresh → 401.
- Password change / deactivation still kills cookie sessions (existing revoke-all semantics).
- CORS: credentialed request from allowlisted origin succeeds; foreign origin gets no CORS
  headers (existing tests, extended with credentials).

## 11. Decision log (this doc)

| Decision | Choice | Alternatives rejected |
|---|---|---|
| CSRF mechanism | Custom-header check (`X-CSRF-Protection`) gated by strict CORS | Double-submit cookie (more moving parts than needed given the CORS invariant); server-side synchronizer tokens (stateful, breaks the JWT model) |
| Cookie contents | Two JWT cookies (access + path-scoped refresh) | Opaque server-side session (new session store + per-request DB read; discards working JWT machinery) |
| Session continuity | Refresh-on-401 with single-flight retry | Proactive timer refresh (expiry bookkeeping, clock skew, no fewer failure modes) |

Found during implementation planning (not owner decisions — defects, corrected before any code
shipped with them):

| Finding | Correction |
|---|---|
| Refresh cookie `Path=/api/v1/auth/refresh` never reaches `/auth/logout`, which needs to read it | Widened to `Path=/api/v1/auth` (§3) |
| `/auth/login` has no prior credential, so it fell outside the CSRF rule entirely, and its form-encoded body is a CORS-safelisted "simple request" — a working login-CSRF/session-fixation vector | `use_cookies=true` requires the CSRF header directly, gated on the flag rather than a resolved credential source (§5, §6) |
