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
