# ADR-0010: Upload finalization is asynchronous, via the worker

**Status:** Accepted · 2026-07-19

## Context

Presigned uploads (ADR-0008) land bytes in `staging` unseen by the API. Someone must then verify
size, compute the content hash, apply dedup (ADR-0006), commit metadata, and charge quota. This
can happen synchronously inside a "complete upload" API call, or asynchronously in the worker.

## Decision

Asynchronous. The complete-upload endpoint validates the session, enqueues a finalize job, and
returns immediately with a "processing" status. The worker streams the staged object, verifies,
dedups, commits, and marks the session done or failed. The SPA polls session status; a file
appears in its folder only after finalize commits.

## Alternatives considered

- **Synchronous commit in the API** — file usable the instant the call returns, simplest mental
  model, and the recommended default; rejected by the owner in favor of keeping hash-the-bytes
  work off API request handlers entirely, uniformly for every file size.

## Consequences

- Upload UX includes a visible "processing" state on every upload — honest and uniform, but a
  state the SPA and API must both model.
- API latency is immune to file size; the worker absorbs verification cost.
- Requires the idempotent-jobs + sweep discipline of ARCHITECTURE §6 (a lost finalize job must be
  caught by the staging sweep and fail the session cleanly).

## Addendum (2026-07-19): no-staging alternative evaluated and rejected

During architecture review the owner challenged the staging concept, asking whether a HEAD
request could replace it. HEAD alone cannot: it returns size and an ETag, but the ETag is MD5
(single-part only), which is neither the SHA-256 the content-addressed layout requires nor
collision-safe enough for cross-user dedup.

A complete no-staging design was then evaluated: the client computes the SHA-256 locally, the API
presigns a PUT **directly to `content/<hash>`** with an `x-amz-checksum-sha256` condition (MinIO
verifies the hash server-side during upload and rejects mismatches), and a synchronous HEAD +
metadata commit replaces the finalize job. Benefits: no staging bucket, no server-side copy, no
"processing" state, and free "instant upload" when the hash already exists. Costs: **every**
client must hash files before uploading (browser needs an incremental/WASM hasher and a full
local read pass; API clients like curl lose plug-and-play uploads), and a single presigned PUT
caps files at 5 GB (multipart + checksums is substantially more complex).

**Rejected** in favor of keeping staging + worker finalize: client-agnostic uploads and no
per-file size ceiling were judged worth the extra moving parts. Revisit if a sync client (which
computes content hashes anyway) becomes the dominant upload path.
