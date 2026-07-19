# Design: Upload and download

| | |
|---|---|
| Status | Approved |
| Feature | File upload/overwrite/download (PRD §5.1, §5.4) |
| ADRs | [0008 presigned data path](../adr/0008-presigned-url-data-path.md), [0010 async finalization](../adr/0010-async-upload-finalization.md) |
| Depends on | `design/storage-model.md` |
| Last updated | 2026-07-19 |

API contract and job specification for the two-phase upload and the presigned download path.
Sharing-aware authorization (editors, link visitors) plugs into these endpoints later via
`design/sharing.md`; v1 of this doc assumes the owner.

## 1. Decisions this doc is built on

| Decision | Choice (owner) | Rejected |
|---|---|---|
| Finalize status delivery | **Polling** (`GET` on the session, ~2 s cadence) | SSE (long-lived connections + worker→API signaling for little gain at this scale) |
| Same-name upload into a folder | **Auto-rename** (`cat.jpg` → `cat (1).jpg`) | Reject with 409 (recommended for explicitness); implicit overwrite (silent data risk) |
| Large files | **Single presigned PUT, 5 GB hard ceiling** (admin max-size setting must be ≤ 5 GB) | S3 multipart (part bookkeeping, abort choreography — deferred until actually needed) |

Corollary of auto-rename: a bare upload can never create a version. **New versions require
explicit intent** — the client initiates the upload with the existing `file_id` instead of
`folder_id + name`. The SPA's "Replace existing?" dialog is exactly that switch.

## 2. Endpoints

All under the existing `/api/v1` prefix, authenticated (cookie or bearer), all error responses in
the standard envelope.

### 2.1 `POST /files/uploads` — initiate

Request (exactly one of the two shapes):

```jsonc
{ "folder_id": "…", "name": "cat.jpg", "size_bytes": 350000 }   // new file
{ "file_id": "…", "size_bytes": 351200 }                        // new version of existing file
```

Server steps (one transaction):
1. Authorize target (owner in v1). Target must be live (not trashed).
2. Validate `size_bytes` > 0, ≤ admin max-file-size (≤ 5 GB hard ceiling).
3. Quota headroom: `used_bytes + size_bytes ≤ effective quota`, else `409 QUOTA_EXCEEDED`
   (details include limit and current usage).
4. New-file shape: resolve name collision against **all live siblings (files and folders)**
   case-insensitively by suffixing before the extension — `cat.jpg`, `cat (1).jpg`,
   `cat (2).jpg`, … The final name is returned; the client does not choose it.
5. Create the `upload_sessions` row (`status = pending`) and presign a PUT for
   `staging/<session_id>` (expiry: `UPLOAD_URL_EXPIRE_SECONDS`, default 3600 — generous for slow
   links).

Response `201`:

```jsonc
{
  "session_id": "…",
  "upload_url": "https://minio…/staging/…?X-Amz-…",
  "url_expires_at": "…",
  "final_name": "cat (1).jpg"     // present for the new-file shape
}
```

### 2.2 Browser → MinIO: `PUT {upload_url}` with the raw bytes

Direct; the API is not involved. MinIO enforces the URL expiry and method. The declared size is
*not* trusted from this step — finalize measures reality.

### 2.3 `POST /files/uploads/{session_id}/complete`

Owner-only, session must be `pending` → sets `processing`, enqueues the finalize job, returns
`202 { "status": "processing" }`. Idempotent: repeat calls while `processing` return the same
202; calls on `done`/`failed` return the terminal status without re-enqueueing.

### 2.4 `GET /files/uploads/{session_id}` — poll

```jsonc
{ "status": "processing" }
{ "status": "done", "file_id": "…", "version_id": "…" }
{ "status": "failed", "failure_reason": "VERIFICATION_FAILED" }
```

SPA guidance: poll every 2 s while `processing`, giving up into an error state after the
staleness window. No other client behavior depends on timing.

### 2.5 `DELETE /files/uploads/{session_id}` — abort

Client-side cancel before/instead of `complete`: marks the session `failed (ABORTED)` and
deletes any staging object. `204`.

### 2.6 `GET /files/{file_id}/download` and `GET /files/{file_id}/versions/{version_id}/download`

Authorize → resolve version → blob hash → respond `200`:

```jsonc
{ "download_url": "https://minio…/content/<hash>?X-Amz-…", "expires_at": "…", "filename": "cat.jpg" }
```

- JSON envelope rather than a 307 redirect: the SPA needs to trigger the browser download
  explicitly and handle errors in-app; API clients follow the URL themselves.
- The presigned GET (expiry `DOWNLOAD_URL_EXPIRE_SECONDS`, default 300) signs
  `response-content-disposition: attachment; filename="…"` so the browser saves the real name,
  not the hash.
- Trashed files: `404` (the item is not live; restore first).

## 3. Finalize job (worker)

Input: `session_id`. Steps:

1. Load session; if not `processing`, exit (idempotency guard — the status transition in 2.3 is
   the single-execution gate, and re-delivered jobs find `done`/`failed` and do nothing).
2. `HEAD staging/<session_id>` — missing object → fail `UPLOAD_INCOMPLETE`.
3. Actual size checks: > 0, ≤ max-file-size → else fail `FILE_TOO_LARGE`.
4. Stream the object once, computing SHA-256 (bounded memory).
5. Dedup: blob row exists for the hash → refcount +1, delete staging. Else server-side copy
   `staging/<id>` → `content/<hash>`, insert blob row (refcount 1), delete staging.
6. Commit metadata in one transaction:
   - re-check quota with the *actual* size (fail `QUOTA_EXCEEDED` if the declared size lied
     — and roll back the refcount/blob step accordingly);
   - new-file shape: insert `files` row (re-resolving the name if a sibling appeared meanwhile)
     + first version; version shape: insert version row, update `current_version_id`, prune
     to the retention limit (oldest version row out, refcount −1);
   - `used_bytes` += actual size (− pruned version's size);
   - session → `done` with `file_id`/`version_id`.
7. Any unexpected error: session → `failed (INTERNAL)`, staging object left for the sweeper,
   refcount effects rolled back with the transaction.

**Sweeper job** (periodic): sessions in `pending`/`processing` older than
`UPLOAD_SESSION_TTL` (default 24 h) → `failed (EXPIRED)` + staging cleanup. This is the backstop
that makes a lost queue message harmless (ARCHITECTURE §6).

## 4. Error catalog (this feature's additions)

| Code | HTTP | When |
|---|---|---|
| `QUOTA_EXCEEDED` | 409 | initiate headroom check, or finalize actual-size re-check |
| `FILE_TOO_LARGE` | 413 | initiate declared size, or finalize actual size |
| `UPLOAD_INCOMPLETE` | (session failure) | complete called but no staging object |
| `VERIFICATION_FAILED` | (session failure) | object unreadable/corrupt during hashing |
| `UPLOAD_SESSION_EXPIRED` | 409 | complete/abort on a swept session |
| `NOT_FOUND` | 404 | unknown/foreign/trashed target |

## 5. Settings added

`UPLOAD_URL_EXPIRE_SECONDS` (3600), `DOWNLOAD_URL_EXPIRE_SECONDS` (300),
`UPLOAD_SESSION_TTL_HOURS` (24), `MAX_FILE_SIZE_BYTES` (admin, ≤ 5 GB enforced), poll cadence is
client-side only.

## 6. Test plan

- Initiate: quota rejection (409 with limits in details), size rejection, auto-rename resolves
  against files *and* folders, `(1)`→`(2)` progression, version-shape targets the file.
- Complete: idempotency (double call, call after done), unknown session, foreign user's session.
- Finalize (worker tests against real MinIO + DB): new-content path, dedup path (refcount 2,
  single object), overwrite path (version added, `current_version_id` moved, prune at 6th
  version, refcount −1 on pruned), size-lie path (declared 100 B, actual over max → failed +
  staging gone), missing staging object, job re-delivery no-op.
- Download: owner gets working URL with attachment filename; old version URL serves old bytes;
  trashed file 404; foreign file 404; expired URL rejected by MinIO (integration smoke).
- Sweeper: stale pending session failed + staging removed; done sessions untouched.
- Invariants of `storage-model.md` §6 hold after every scenario above.

## 7. Out of scope

Folder (zip) download — not in the PRD MVP. Multipart uploads — revisit only if the 5 GB ceiling
actually pinches. Editor/link-visitor authorization on these endpoints — `design/sharing.md`.
