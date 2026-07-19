# ADR-0011: Separate origins for SPA, API, and MinIO (CORS)

**Status:** Accepted · 2026-07-19

## Context

Three surfaces face the browser: the SPA's static assets, the REST API, and MinIO's S3 port (for
presigned requests). They can share one origin behind a reverse proxy, or each keep their own
origin with CORS bridging the gaps.

## Decision

Separate origins. Each service is exposed on its own host/port; the browser crosses origins under
CORS. The API keeps its existing strict-allowlist CORS (exact origins, credentials allowed, never
`*`); MinIO gets a CORS policy permitting presigned PUT/GET from the SPA origin only.

## Alternatives considered

- **Reverse proxy, single origin** — no CORS in production, one TLS point, and the recommended
  default; rejected by the owner in favor of simpler per-service containers and explicit
  service-level exposure.
- **API serves the SPA build** — mixes concerns and still leaves MinIO cross-origin; solves the
  least of the problem.

## Consequences

- No proxy container; each service's exposure is explicit and independently scalable.
- CORS configuration becomes production-critical on two services (API, MinIO).
- Combined with cookie sessions (ADR-0012): cross-origin credentialed requests require
  `SameSite=None; Secure` cookies — hence HTTPS on all three origins in any non-localhost
  deployment, and CSRF protection on the API.
