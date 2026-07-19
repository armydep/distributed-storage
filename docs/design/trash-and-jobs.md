# Design: Trash lifecycle and the background job suite

| | |
|---|---|
| Status | Approved |
| Feature | Trash (PRD §5.5) + all periodic cleanup jobs |
| ADRs | [0006 refcounted dedup](../adr/0006-refcounted-dedup.md), [0007 worker/arq/Redis](../adr/0007-dedicated-worker-arq-redis.md) |
| Depends on | `design/storage-model.md`, `design/upload-download.md` (finalize job + sweeper already defined there) |
| Last updated | 2026-07-19 |

## 1. Decisions this doc is built on

| Decision | Choice (owner) | Rejected |
|---|---|---|
| Permanent delete / empty trash execution | **Always async via worker** — endpoint enqueues, returns 202 | Synchronous with a size cap (recommended: instant for the common case; rejected in favor of a uniform, never-slow API) |
| GC safety window (refcount 0 → physical delete) | **24 hours** | 1 hour (less cushion); 7 days (holds reclaimable space longest) |
| Restore into a folder with a same-named live item | **Auto-rename** (see worked example below) — consistent with upload | Fail and ask the user (more deliberate; restore stops being one-click) |

Consequence of "always async": trash/empty-trash gain a **"purging"** state in the API/UI,
mirroring the upload "processing" state — the product now has two places where an action returns
immediately and the result appears shortly after. Both use the identical polling pattern.

**Restore conflict, worked example** (for anyone reading this doc cold): Alice deletes
`Photos/cat.jpg` on Monday (flagged, not renamed). Tuesday she uploads a different photo also
named `cat.jpg` into `Photos/` — allowed, since the trashed one isn't a live sibling. Wednesday
she restores Monday's `cat.jpg`; `Photos/` already has a live `cat.jpg`. Auto-rename means it
reappears as `Photos/cat (1).jpg` immediately, same mechanism as upload's collision handling.

## 2. Trash API

### 2.1 `POST /files/{id}/trash`, `POST /folders/{id}/trash`

Sets `trashed_at` + `original_parent_id`/`original_folder_id` on the target row only (per
`storage-model.md` §4 — descendants are implicitly trashed via ancestor visibility, no cascade
write). Synchronous — this is a single-row update regardless of subtree size. `200` with the
updated item. Idempotent on an already-trashed item (no-op, same response).

### 2.2 `GET /trash`

Lists the caller's **top-level trashed items only** (folders and files whose *own* `trashed_at`
is set — a file trashed as part of a folder doesn't get its own row here, it's implied):

```jsonc
{
  "items": [
    { "id": "…", "type": "folder", "name": "Old Project", "trashed_at": "…", "expires_at": "…",
      "original_path": "Work/Old Project", "size_bytes": 48291012 },
    { "id": "…", "type": "file", "name": "cat.jpg", "trashed_at": "…", "expires_at": "…",
      "original_path": "Photos/cat.jpg", "size_bytes": 350000 }
  ],
  "pagination": { … }
}
```

- `expires_at` = `trashed_at` + trash retention (default 30 days, admin-configurable) — the SPA
  shows "auto-deletes in N days."
- `size_bytes` for a trashed folder is the live sum over its subtree at trash time (computed via
  the same `path <@` query as `storage-model.md` §4); not recomputed afterward — content inside a
  trashed folder cannot change.
- `original_path` is best-effort display (built from `original_parent_id` + ancestor names at
  query time); if an ancestor no longer exists the path shown is truncated with an indicator —
  restore still works via §2.3's fallback.

### 2.3 `POST /trash/{id}/restore`

1. Clear `trashed_at`.
2. Target parent = `original_parent_id`/`original_folder_id` if that folder still exists **and**
   is itself live; otherwise the user's root (fallback).
3. Auto-rename against live siblings at the resolved target, exactly as upload-download.md §2.1
   step 4 (same shared name-resolution routine).
4. `200` with the restored item's new location.

Synchronous — restore, like trash, is a metadata-only operation independent of subtree size.

### 2.4 `DELETE /trash/{id}` (permanent delete, one item) and `DELETE /trash` (empty trash, all)

Both **enqueue** a purge job and return `202 { "purge_id": "…" }` (owner decision: always async).
`GET /trash/purges/{purge_id}` polls status (`processing` / `done` / `failed`), same shape as the
upload-session poll endpoint. The trash listing (§2.2) excludes items with an in-flight purge.

## 3. Background job suite (arq, per ADR-0007)

All jobs are idempotent (safe to run twice) and every queued one has a periodic backstop, per
ARCHITECTURE §6. Cadences below are defaults exposed as settings.

| Job | Trigger | Cadence | Does |
|---|---|---|---|
| **Upload finalize** | queued (upload complete) | — | Defined in `upload-download.md` §3 |
| **Upload sweep** | periodic | hourly | Defined in `upload-download.md` §3 (stale sessions) |
| **Trash purge** | queued (§2.4) **and** periodic | on-demand + daily | See §3.1 |
| **Blob GC** | periodic | hourly | See §3.2 |
| **Reconciliation** | periodic | daily | See §3.3 |

### 3.1 Trash purge job

Input: either an explicit `(purge_id, item_id)` from §2.4, or — for the daily periodic run — the
set of trashed items past `expires_at`.

Per item, one transaction:
1. Resolve the full subtree (files directly, plus files under any trashed descendant folders via
   the `path <@` query).
2. For every file: delete its version rows, decrement each referenced blob's refcount,
   decrement `owner.used_bytes` by each version's size.
3. Delete the file rows, then the folder rows (descendants before the top item — FK order), or
   the single file row.
4. Mark the purge (`purge_id`) `done`, or — for periodic runs — nothing to report back to (no
   session object; just gone).

No MinIO I/O here — only DB rows and refcounts change. Zero-refcount blobs become Blob GC's job,
not this one's. This keeps the purge job fast and simple regardless of how many blobs it
dereferences.

### 3.2 Blob GC job

1. Select blobs with `refcount = 0` **and** `updated_at < now() - 24h` (the safety window —
   owner decision — catching any blob that hit zero and stayed there, not just ones that hit
   zero this run).
2. Per blob: `DELETE content/<hash>` from MinIO, then delete the blob row. Object-then-row order:
   if the job dies between the two, the next run finds a DB row with no object — treated as
   already-effectively-deleted, row cleanup retried; never the reverse (a row-then-object death
   would leave the blob invisible to the app but still billed nowhere, i.e. actually fine either
   way — chosen order just avoids a dangling reference being followed).
3. Metrics: objects deleted, bytes reclaimed — logged for operator visibility.

### 3.3 Reconciliation job

Read-only correction pass, the system's self-check:

1. **Refcount drift:** for each blob, recompute `COUNT(*) FROM file_versions WHERE blob_hash = …`
   and compare to the stored `refcount`. Mismatches are corrected and logged at `WARNING` — this
   should never fire in a healthy system; if it does, it's the signal a refcount bug exists.
2. **Quota drift:** for each user, recompute `SUM(size_bytes)` over their versions and compare to
   `used_bytes`; correct and log on mismatch, same severity.
3. Runs daily; cheap at personal-cloud data volumes (full scan of `file_versions`, indexed
   aggregates).

## 4. Settings added

`TRASH_RETENTION_DAYS` (30, admin), `BLOB_GC_SAFETY_WINDOW_HOURS` (24), `TRASH_PURGE_CADENCE`
(daily), `BLOB_GC_CADENCE` (hourly), `RECONCILIATION_CADENCE` (daily).

## 5. Test plan

- Trash/restore are synchronous and instant regardless of subtree size (integration test with a
  deep folder — timing assertion, not just correctness).
- Trash listing shows only top-level items; a file trashed inside a trashed folder never appears
  independently.
- Restore: original location intact → goes back exactly there; original folder gone → falls back
  to root; name collision at target → auto-renamed (the worked example, as a test).
- Purge (single + empty-trash): enqueues, polls to `done`; verifies every descendant version/row
  gone, every referenced blob's refcount decremented, `used_bytes` reduced correctly; a blob
  shared with another user's *live* file keeps refcount ≥ 1 and is not deleted.
- Blob GC: a blob at refcount 0 younger than 24h is left alone; older than 24h is deleted from
  both MinIO and the DB; a blob that regains a reference before the window elapses is skipped.
  Job re-run after a simulated mid-job crash (object deleted, row not) completes cleanly.
- Reconciliation: seeded drift (manually corrupt a refcount / used_bytes in a test) is detected,
  corrected, and logged; a healthy dataset reports zero corrections.
- All `storage-model.md` §6 invariants re-verified after every scenario above.

## 6. Out of scope

Per-user trash retention overrides (service-wide only in v1). Undo-purge (permanent means
permanent, per PRD). Folder-download-as-zip touching purge timing — not in MVP.
