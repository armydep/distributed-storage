# ADR-0008: File bytes travel via presigned URLs

**Status:** Accepted · 2026-07-19

## Context

With an S3-compatible store (ADR-0003), file bytes can either be proxied through the API
(browser ↔ API ↔ MinIO) or flow directly between browser and MinIO using presigned URLs issued by
the API after authorization.

## Decision

Presigned URLs, both directions. Uploads PUT directly to the `staging` bucket; downloads GET
directly from `content` with a short expiry and the proper download filename. The API remains the
sole authorizer — it signs nothing without an ownership/share/link check — but never carries file
payloads.

## Alternatives considered

- **Proxy through the API** — single enforcement point, MinIO stays private, and was the
  recommended default at self-hosted scale; rejected by the owner in favor of taking file
  bandwidth off the API from day one.

## Consequences

- API request handling stays light regardless of file sizes; large uploads can't exhaust API
  workers.
- MinIO's S3 port becomes browser-reachable (drives ADR-0011) and needs CORS + deny-anonymous
  bucket policies; presigned expiries are the blast radius of a leaked URL.
- The API never sees uploaded bytes → size/hash verification must happen post-upload, which
  forces the two-phase upload of ADR-0010.
