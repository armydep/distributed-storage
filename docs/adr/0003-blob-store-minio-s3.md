# ADR-0003: File bytes in an S3-compatible object store (MinIO)

**Status:** Accepted · 2026-07-19

## Context

File contents (GBs to low TBs at v1 scale) need a home. The deployment is self-hosted Docker
Compose today, but the owner wants cloud portability rather than the absolute minimum footprint.

## Decision

Store all file bytes in MinIO, accessed exclusively through the S3 API. Two buckets: `staging`
(in-flight uploads, sweepable) and `content` (finalized, content-addressed, backup-worthy). The
application depends on the S3 protocol, not on MinIO specifically.

## Alternatives considered

- **Local filesystem** — simplest for single-node self-hosting and was the recommended default;
  rejected by the owner in favor of cloud portability and presigned-URL capability (ADR-0008
  depends on an S3-style store).
- **PostgreSQL BLOBs** — anti-pattern at GB file sizes: DB bloat, memory pressure, painful dumps.

## Consequences

- Swapping MinIO for AWS S3/R2/GCS-interop later is configuration, not code.
- Presigned URLs (ADR-0008) become possible at all.
- One more stateful service to run and back up; MinIO's S3 port becomes browser-reachable
  (ADR-0011), which shapes the security posture.
