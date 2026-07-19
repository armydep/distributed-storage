# Design: Sharing (user-to-user shares and public links)

| | |
|---|---|
| Status | Approved |
| Feature | Sharing (PRD §5.3) |
| Depends on | `design/storage-model.md` (polymorphic-reference pattern), `design/upload-download.md`, `design/trash-and-jobs.md` |
| Last updated | 2026-07-19 |

Defines the data model, resolution algorithm, and API for both sharing mechanisms, and how they
plug into the endpoints already specified elsewhere (upload/download/trash all gain a share-aware
authorization step here).

## 1. Decisions this doc is built on

| Decision | Choice (owner) | Rejected |
|---|---|---|
| Share resolution | **Live ancestor-path query** at request time — same mechanism as trash visibility | Materialized effective-permissions table (faster reads, second source of truth to keep in sync) |
| Link token storage | **Hash-only** (SHA-256), same precedent as refresh tokens | Store raw token (simpler "view again" UX, but a DB leak exposes working links) |
| Re-sharing | **Owner-only** — editors cannot create or manage shares/links | Editors can re-share (more flexible, access can spread beyond what the owner directly granted) |
| Conflicting grants | **Most permissive wins** across all applicable grants | Most specific wins (more precise, less intuitive) |

## 2. Tables

### 2.1 `shares` (user-to-user)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `file_id` | UUID FK → files, nullable | |
| `folder_id` | UUID FK → folders, nullable | `CHECK ((file_id IS NULL) <> (folder_id IS NULL))` — the polymorphic pattern `storage-model.md` flagged |
| `owner_id` | UUID FK → users | denormalized: always the item's owner at share time (owner cannot change without unsharing — ownership never transfers) |
| `grantee_id` | UUID FK → users | the recipient |
| `permission` | ENUM `viewer / editor` | |
| `created_at` / `updated_at` | | |

Constraint: unique `(file_id, folder_id, grantee_id)` — one active grant per (item, person); a
second share call on the same pair updates `permission` rather than duplicating.

### 2.2 `share_links` (public links)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `file_id` | UUID FK → files, nullable | same polymorphic CHECK as `shares` |
| `folder_id` | UUID FK → folders, nullable | |
| `owner_id` | UUID FK → users | |
| `token_hash` | TEXT, unique | SHA-256 hex of the raw token — owner decision |
| `expires_at` | TIMESTAMPTZ, nullable | NULL = no expiry |
| `revoked_at` | TIMESTAMPTZ, nullable | |
| `created_at` | | |

Links are always **viewer-equivalent** (list/download only) — the PRD never proposes an editable
public link, and allowing anonymous edits isn't on the table.

## 3. Token handling

Raw token: 32 bytes of `secrets.token_urlsafe`, returned **exactly once**, in the create-link
response, embedded in the shareable URL (`https://…/s/<raw_token>`). Only `sha256(raw_token)` is
stored — identical precedent to refresh tokens (`core/security.py::hash_refresh_token`, reused
directly here rather than duplicated). Lookup on link access: `hash(presented_token) == token_hash
AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`; any failure is a uniform
`404` (not `403` — a wrong or dead link should not confirm anything ever existed there, matching
the reasoning already applied to link resolution in `upload-download.md`'s trashed-file 404).

## 4. Resolution algorithm (the live ancestor-path query)

Given a user `U` and a target item `I` (file or folder), compute the effective permission:

```sql
-- Grants on I itself, or on any ancestor folder of I, for user U:
WITH ancestor_folders AS (
    SELECT id FROM folders
    WHERE path @> (SELECT COALESCE(  -- @> = "is an ancestor of"
        (SELECT path FROM folders WHERE id = :folder_id_of_I),
        (SELECT d.path FROM files f JOIN folders d ON d.id = f.folder_id WHERE f.id = :file_id_of_I)
    ))
)
SELECT permission FROM shares
WHERE grantee_id = :U
  AND ( file_id = :file_id_of_I
        OR folder_id = :folder_id_of_I
        OR folder_id IN (SELECT id FROM ancestor_folders) );
```

- **Owner** always has full (implicit "owner" level, superset of editor) access — checked first,
  short-circuiting the query above entirely.
- **Most permissive wins**: if the query returns more than one row (direct grant + inherited
  grant, or multiple inherited grants at different levels), take `MAX(editor > viewer)`.
- **Trash interaction**: an item inside a trashed folder resolves permission the same way, but
  visibility is independently gated by the trash ancestor-check from `storage-model.md`/`trash-
  and-jobs.md` — a trashed item is invisible to everyone including grantees until restored (PRD
  §5.5: "shared access is suspended while in trash").
- **Deleted-by-editor-goes-to-owner's-trash** (PRD §5.3): enforced in the delete endpoint itself,
  not here — it always trashes into the *owner's* trash tree regardless of who performed the
  delete, which the endpoint achieves by using the owner's root as the trash target rather than
  the actor's.

This query runs once per authorization check, same cost class as the trash ancestor-check already
in the codebase; no caching in v1 — revisit only if profiling shows it matters.

## 5. Endpoints

### 5.1 `POST /files/{id}/shares`, `POST /folders/{id}/shares` — grant

Owner-only (enforced by the auth dependency chain, consistent with the platform's RBAC pattern).

```jsonc
{ "grantee_username": "bob", "permission": "editor" }
```

`201` with the share; `409 SHARE_ALREADY_EXISTS` is impossible by design (upsert-on-conflict per
§2.1's unique constraint — a repeat call updates permission and returns `200`).
`404 NOT_FOUND` if the grantee doesn't exist or the target isn't live.

### 5.2 `PATCH /shares/{id}` — change permission, `DELETE /shares/{id}` — revoke

Owner-only. `204` on delete. Revoking a folder share revokes the *entire inherited grant* for
that user on that subtree in one row-delete — no cascade needed, since inheritance is computed
live (§4), not stored per-descendant.

### 5.3 `GET /shares/mine` — shares I created (owner's management view)

Lists every `shares` row where `owner_id = caller`, grouped by item, so the owner can audit "who
has access to what."

### 5.4 `GET /shared-with-me`

Lists items where the caller is a grantee — **top-level grants only** (an item inherited via a
folder grant doesn't get its own row; opening the shared folder reveals its contents through the
normal folder-listing endpoint, which now also checks §4 for non-owned folders). Each entry shows
the effective permission and the granting owner.

### 5.5 `POST /links`, `GET /links/mine`, `PATCH /links/{id}` (expiry), `DELETE /links/{id}`

Owner-only management, mirroring §5.1–5.2. `POST /links` response includes the raw token exactly
once (§3); subsequent `GET /links/mine` entries show only `id`, target, `expires_at`,
`created_at` — never the token.

### 5.6 `GET /s/{token}` — resolve and use a link (no auth required)

1. Look up by `hash(token)`; not found/expired/revoked → `404`.
2. Target is a file → same shape as `upload-download.md` §2.6 (presigned download URL).
3. Target is a folder → a listing endpoint scoped to that folder's subtree (read-only, no
   `folder_id`-based navigation outside it), each entry itself resolvable through the same link
   for nested downloads. Folder links expose the whole tree including items added later (PRD
   §5.3), which falls out naturally: the listing is always computed live against current contents.
4. Trashed target → `404` (§4).

### 5.7 Authorization changes to existing endpoints

Every endpoint that currently checks "is this item owned by the caller" (file/folder read, list,
download, and — for editors only — rename/move/overwrite/delete from `upload-download.md` and
`trash-and-jobs.md`) is extended to: **owner, OR §4 resolves a sufficient permission.** Viewer
permission covers read endpoints; editor additionally covers write endpoints; trash/permanent-
delete/share-management remain owner-only regardless of editor status (§5.2, and PRD's "ownership
never transfers").

## 6. Test plan

- Grant/revoke/update a share; repeat-grant upserts rather than duplicating.
- Direct file share (viewer) grants read but not write; editor share grants both.
- Folder share inheritance: granting on a folder gives access to files added to it *after* the
  grant (live query, no backfill needed — the defining test of this design).
- Most-permissive-wins: direct viewer grant on a file + editor grant on its parent folder →
  effective editor (per the owner's decision).
- Editor cannot create/revoke shares or links (owner-only enforcement).
- Editor delete inside a shared folder lands in the *owner's* trash, not the editor's.
- Trashing the shared folder suspends all grantee access (§4 interaction); restoring resumes it.
- Link: create → token works; wrong token → 404; revoked → 404; expired → 404; folder link lists
  live contents added after link creation; download via link never exposes the DB token, only the
  presigned MinIO URL.
- `GET /shared-with-me` shows top-level grants only, not every descendant individually.
- Cross-check against `storage-model.md` §6 invariants — none of them are affected by sharing
  (shares don't change ownership, refcounts, or quota), which is itself worth asserting.

## 7. Out of scope

Share notifications (email/in-app) — not in the PRD. Granular per-operation permissions beyond
viewer/editor. Time-limited user-to-user shares (only links support expiry, per PRD §5.3).
