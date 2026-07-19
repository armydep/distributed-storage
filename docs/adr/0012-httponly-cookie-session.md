# ADR-0012: SPA authentication via httpOnly cookie session

**Status:** Accepted · 2026-07-19

## Context

The API's OAuth2 bearer-JWT flow with rotating refresh tokens is already built. The React SPA
(ADR-0009) must hold a session somehow: bearer tokens in JS memory, or cookies the browser manages.

## Decision

httpOnly cookies. The API sets access/refresh material in httpOnly cookies on login and reads them
on authenticated requests; the SPA's JavaScript never sees a token. Existing semantics —
short-lived access, rotating single-use refresh, server-side revocation — are preserved behind the
cookie surface. The bearer-token flow remains available for non-browser API clients; cookies are
an additional transport, not a replacement.

## Alternatives considered

- **Bearer JWT in SPA memory** — uses the API exactly as built, immune to CSRF, and the
  recommended default; rejected by the owner in favor of XSS-resistant token storage and sessions
  that survive page reloads without a refresh round-trip.

## Consequences

- Tokens are unreachable from JavaScript — XSS cannot exfiltrate them (it can still act in-page,
  which is why CSP and dependency hygiene still matter).
- Cookies attach automatically → the API must add CSRF protection for state-changing requests,
  and cross-origin operation (ADR-0011) forces `SameSite=None; Secure` + HTTPS.
- The auth module needs a designed extension (cookie issuance/refresh/logout paths) — the subject
  of the auth design doc before any storage feature ships.
