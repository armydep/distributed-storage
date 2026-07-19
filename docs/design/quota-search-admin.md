# Design: Quota, search, and admin extensions

| | |
|---|---|
| Status | Approved |
| Feature | Quotas & limits (PRD §5.6), search (§5.7), admin extensions (§5.9) |
| Depends on | `design/storage-model.md` (used_bytes, quota_bytes), `design/upload-download.md` (quota enforcement points), `design/sharing.md` (search scope) |
| Last updated | 2026-07-19 |

The three smallest remaining backend features — grouped because none needs its own doc, and quota
settings, search scope, and admin visibility all read from state already defined elsewhere.

## 1. Decisions this doc is built on

| Decision | Choice (owner) | Rejected |
|---|---|---|
| Service-wide settings storage | **Environment variables**, same as the rest of the platform (`core/config.py::Settings`) | DB-backed settings table (recommended for in-app runtime edits without a restart) |
| Search matching | **Plain `ILIKE`, unindexed** | `pg_trgm` trigram GIN index (indexed substring search, extra extension + maintenance overhead) |
| Admin usage view | **Total only** (`used_bytes` vs `quota_bytes`) | Breakdown by live/versions/trash (more diagnostic insight, needs extra aggregate queries) |

**Consequence worth flagging explicitly:** the PRD (§5.9) describes the admin "configuring
service-wide defaults" as an in-product capability. With settings as environment variables, this
becomes an **operator/deployment action** (edit `.env`, restart the `api` and `worker`
containers) rather than something exposed through the admin API or UI. The web UI's admin screen
will *display* current effective values (read-only) but not let an admin change them in-browser.
This is a scope reduction from a literal reading of §5.9 — flagged here rather than silently
narrowed, in case it's revisited once the admin UI is actually being built.

## 2. Settings (environment variables, extending `.env.example`)

| Setting | Default | Used by |
|---|---|---|
| `DEFAULT_QUOTA_BYTES` | 10 GiB | quota check, applies when `users.quota_bytes IS NULL` |
| `MAX_FILE_SIZE_BYTES` | 2 GiB (≤ 5 GiB hard ceiling per `upload-download.md`) | upload initiate + finalize |
| `VERSION_RETENTION_COUNT` | 5 | finalize prune step (`upload-download.md` §3) |
| `TRASH_RETENTION_DAYS` | 30 | trash purge (`trash-and-jobs.md` §3.1) |

All already referenced by name in earlier docs; this table is their single canonical definition
point, added to `Settings` alongside the platform's existing config validation (production-safety
checks apply the same way — e.g. a nonsensical `VERSION_RETENTION_COUNT=0` fails startup).

**Per-user override stays in the database**, unaffected by this decision: `users.quota_bytes`
(nullable — NULL defers to `DEFAULT_QUOTA_BYTES`) continues to be admin-editable *per user*
through the existing admin user-management endpoints (`PATCH /users/{id}` already exists on the
platform; this feature adds `quota_bytes` as one more field it accepts, exactly like `is_active`
and `role` today).

## 3. Quota endpoints

### 3.1 `GET /users/me/usage`

```jsonc
{ "used_bytes": 4831200, "quota_bytes": 10737418240 }
```

`quota_bytes` is the effective value (`users.quota_bytes` or `DEFAULT_QUOTA_BYTES`). Backs the
usage indicator in the PRD's minimal web UI (§5.8).

### 3.2 `GET /admin/users/{id}/usage` (admin-only)

Same shape as §3.1, for any user — the "total only" view. No new aggregation: both fields are
already maintained columns (`storage-model.md` §3.6), so this is a single-row lookup, not a query
over the user's files.

### 3.3 Quota changes (reuses existing admin user endpoints)

`PATCH /users/{id}` gains `quota_bytes` (nullable — set to `null` to revert to the default). No
new endpoint. Setting a quota **below** current usage is allowed (not rejected): the user simply
can't upload further until they free space — nothing is retroactively deleted or force-pruned.
This mirrors how the platform already treats `is_active` transitions (state changes, not data
changes).

## 4. Search

### 4.1 `GET /search?q=<term>&page=&page_size=`

Scope: everything the caller can currently read — own items, plus everything resolvable through
`sharing.md` §4 (direct grants and folder-inherited grants), minus trash.

Query shape (four unioned branches, each an indexed-by-owner/grantee, unindexed-by-name scan):

```sql
-- 1. Own folders                         2. Own files
SELECT id,'folder',name FROM folders      SELECT id,'file',name FROM files
WHERE owner_id=:u AND name ILIKE :q       WHERE owner_id=:u AND name ILIKE :q
  AND <live per storage-model §4>           AND <live per storage-model §4>

-- 3. Directly shared items (files + folders, from `shares` where grantee_id=:u)
-- 4. Items under any folder shared with :u (path <@ each shared folder's path, from sharing §4)
```

Branches 3–4 reuse the exact grant lookup from `sharing.md` §4 rather than re-deriving it —
search's "what can I see" and download's "am I allowed" are the same question asked in bulk vs.
one-at-a-time. Results merged, deduplicated (an item reachable two ways appears once), paginated,
ordered by name.

Each result includes enough to place it: `path` (own items) or `owner + shared-via` (shared
items), matching the PRD's "results show enough context... to identify the file and jump to it."

### 4.2 Why unindexed is fine here (owner decision, with the reasoning made explicit)

`ILIKE '%term%'` cannot use a standard btree index (leading wildcard), so every search is a scan
— but it's a scan bounded by **one user's own item count plus their shared scope**, not the whole
table (branches 1–2 are already filtered by `owner_id`; branches 3–4 by `grantee_id`/shared-folder
membership before the name filter applies). At the PRD's target scale (tens of users, GBs–low TBs)
that bound is at most a few thousand rows — a sequential scan over a few thousand rows is
single-digit milliseconds. Revisit with `pg_trgm` only if real usage shows otherwise; the query
shape doesn't need to change, only the index backing it.

## 5. Test plan

- Usage endpoint reflects `used_bytes`/effective `quota_bytes` immediately after an upload,
  version prune, or trash purge (cross-check against `storage-model.md` §6 invariant 4).
- Admin usage view for another user returns the same numbers that user's own `/users/me/usage`
  would show; non-admin gets `403`.
- `PATCH /users/{id}` with `quota_bytes` below current usage succeeds; a subsequent upload that
  would exceed it is rejected (`QUOTA_EXCEEDED`, per `upload-download.md` §4); existing files
  untouched.
- `quota_bytes: null` reverts to `DEFAULT_QUOTA_BYTES`.
- Search: matches substrings case-insensitively; excludes trashed items; includes items shared
  directly and items under a shared folder (including ones added after the share, consistent with
  `sharing.md`'s inheritance test); excludes items shared with *other* users; pagination stable
  across pages.
- Config validation: `VERSION_RETENTION_COUNT=0` or negative, `MAX_FILE_SIZE_BYTES` above the 5
  GiB ceiling, or `TRASH_RETENTION_DAYS=0` all fail startup (extends the existing
  `_validate_production_safety`-style checks).

## 6. Out of scope

In-app editing of service-wide defaults (per §1's flagged consequence — revisit if wanted later,
at which point it becomes "add a settings table," a small, additive change, not a redesign).
Search result ranking/relevance beyond substring match. Search inside file contents (explicit PRD
non-goal).
