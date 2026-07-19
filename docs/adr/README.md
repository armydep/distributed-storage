# Architecture Decision Records

One record per significant decision. Accepted ADRs are immutable — course changes get a new ADR
that supersedes the old one. Format and rationale: [ADR-0001](0001-record-architecture-decisions.md).

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions as ADRs | Accepted |
| [0002](0002-metadata-in-postgresql.md) | All metadata in the existing PostgreSQL | Accepted |
| [0003](0003-blob-store-minio-s3.md) | File bytes in an S3-compatible store (MinIO) | Accepted |
| [0004](0004-content-addressed-blob-layout.md) | Content-addressed blob layout | Accepted |
| [0005](0005-whole-file-blobs.md) | Whole-file blobs, no chunking in v1 | Accepted |
| [0006](0006-refcounted-dedup.md) | Reference-counted deduplication in v1 | Accepted |
| [0007](0007-dedicated-worker-arq-redis.md) | Dedicated worker service on arq + Redis | Accepted |
| [0008](0008-presigned-url-data-path.md) | File bytes travel via presigned URLs | Accepted |
| [0009](0009-react-spa-frontend.md) | React SPA (TypeScript + Vite) web UI | Accepted |
| [0010](0010-async-upload-finalization.md) | Asynchronous upload finalization via worker | Accepted |
| [0011](0011-separate-origins-cors.md) | Separate origins for SPA/API/MinIO (CORS) | Accepted |
| [0012](0012-httponly-cookie-session.md) | SPA auth via httpOnly cookie session | Accepted |
