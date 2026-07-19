# Product Requirements Document — Distributed Storage

| | |
|---|---|
| Status | Approved |
| Version | 1.0 |
| Owner | armydep |
| Last updated | 2026-07-19 |

## 1. Overview

A self-hosted personal cloud storage service — in the spirit of Dropbox or Google Drive, but owned
and operated by the individual or household running it. Users store files and folders, access them
from any browser or HTTP client, share them with other people, and recover earlier versions of
their files or items they deleted.

This document defines **what** the product does and for whom. It deliberately contains no
technology or implementation decisions; those are recorded separately in `docs/ARCHITECTURE.md` and
`docs/adr/`.

## 2. Target users

**Primary: the self-hosting individual.** A technically comfortable person running the service on
their own hardware or VPS for themselves, family, or a small circle of friends. They value data
ownership and privacy over polish, but still expect the core flows to be reliable and obvious.

**Secondary: invited users.** People the primary user creates accounts for (family members,
friends). They interact through the web UI, are less technical, and never touch the server.

**Tertiary: the administrator.** Usually the same person as the primary user, wearing a different
hat: creates accounts, sets quotas, deactivates users. Admin capabilities already exist in the
platform and are extended, not rebuilt, by this product.

## 3. Goals

1. A user can store their personal files on a server they control and retrieve them from any
   device with a browser.
2. Files are organized in familiar folder hierarchies with the operations people expect: create,
   rename, move, delete.
3. A user can share any file or folder — either with another registered user or with anyone via a
   link — and can revoke that access at any time.
4. Data loss requires deliberate effort: overwrites are covered by versioning, deletions by a
   30-day trash. Nothing disappears from a single click.
5. The administrator can bound disk consumption per user and per file, and users can see their own
   usage.
6. A user can find their files by name without remembering where they put them.

## 4. Non-goals (v1)

Explicitly out of scope for the first version. Listing these here is the contract that prevents
scope creep; moving any of them into scope requires a PRD revision.

- **Desktop or mobile sync clients** (Dropbox-style folder synchronization, conflict resolution,
  delta sync). The web UI and API are the only access paths in v1.
- **Real-time collaboration or in-browser editing** of documents.
- **File previews** (image thumbnails, PDF rendering) in the web UI.
- **Content search** (inside documents), OCR, or ML-based features. Search is filename-only.
- **End-to-end encryption** where the server cannot read file contents. (Transport encryption and
  at-rest protections are architecture concerns, not excluded — this non-goal is specifically
  about E2EE.)
- **Multi-region or high-availability deployment.** v1 targets a single self-hosted node.
- **Third-party identity providers** (Google/GitHub login). Local accounts only, as already built.
- **Payments, plans, or any monetization.**

## 5. MVP features

The MVP is what v1 ships. Features are listed with product-level acceptance criteria; API shapes,
data models, and storage mechanics belong to the design docs.

### 5.1 Files

- Upload a file into any folder the user owns (subject to quota and max-file-size limits).
- Download a file the user owns or has access to via sharing.
- Rename and move files within the user's own hierarchy.
- Delete a file — a soft delete: the file moves to the owner's trash (§5.5) and can be restored
  for 30 days.
- Every file has visible metadata: name, size, containing folder, created/modified timestamps.

### 5.2 Folders

- Nested folder hierarchy per user, rooted at a personal root folder.
- Create, rename, move, and delete folders. Deleting a folder moves it — with its entire contents
  — to trash as a single restorable unit.
- List a folder's contents, ordered sensibly (folders first, then files; name order).

### 5.3 Sharing

Two sharing mechanisms, both first-class in the MVP:

**Public links.** Any file or folder can be shared via a generated, unguessable link.
- Anyone holding the link can view/download the target without an account. A folder link exposes
  the entire folder tree, including items added after the link was created.
- The owner can set an optional expiry when creating the link and can revoke it at any time;
  revoked or expired links stop working immediately.
- The owner can list all links they have created and see each link's target and status.

**User-to-user shares.** Any file or folder can be shared with a specific registered user.
- Permission levels:
  - **Viewer** — list and download the shared content.
  - **Editor** — everything a viewer can do, plus upload, rename, move, overwrite, and delete
    within the shared scope. Deletions performed by an editor land in the **owner's** trash, so
    the owner can always undo them.
- The recipient sees content shared with them in a dedicated "Shared with me" area, distinct from
  their own hierarchy.
- The owner can change a share's permission level or revoke it at any time; ownership never
  transfers.
- Sharing a folder covers everything inside it, including items added later.

### 5.4 File versioning

- Overwriting an existing file (same name, same folder) creates a new version rather than
  destroying the previous content.
- Users can list a file's versions (with timestamp and size), download any retained version, and
  restore a previous version to become the current one. Restoring is itself a version-creating
  event — it never erases history within retention.
- **Retention: last N versions per file** (default **5**, administrator-configurable
  service-wide). When the limit is exceeded, the oldest version is removed.
- Version storage counts toward the owner's quota.

### 5.5 Trash

- Deleting a file or folder moves it to the owner's trash rather than destroying it.
- Trash retention: **30 days** (administrator-configurable service-wide). After that, items are
  permanently removed automatically.
- Users can list their trash, restore an item (back to its original location, or to the root if
  that location no longer exists), or permanently delete it immediately ("empty trash" for
  everything at once).
- Trashed items still count toward the owner's quota until permanently removed — emptying trash
  is how a user reclaims space.
- Shared access to an item is suspended while it is in trash and resumes if restored.

### 5.6 Quotas and limits

- **Per-user storage quota**, administrator-configurable per user with a service-wide default. An
  upload that would exceed the quota is rejected with a clear message; nothing is partially stored.
- **Maximum single-file size**, service-wide, administrator-configurable.
- Users can always see their current usage and quota (both API and UI); versions and trashed items
  are included in usage.

### 5.7 Search

- Filename search across everything the user owns and everything shared with them. Trash is
  excluded from search (it has its own listing).
- Case-insensitive substring matching; results show enough context (path, owner if shared) to
  identify the file and jump to it.

### 5.8 Web UI

A minimal but complete file manager — every MVP capability above is usable by a non-technical
person from a browser:

- Login / logout (existing auth).
- Folder browsing with breadcrumb navigation.
- Upload, download, rename, move, delete.
- Trash view: list, restore, permanently delete, empty trash.
- Share dialog: create/revoke links, manage user-to-user shares and permission levels.
- Version list per file with download-old-version and restore.
- Usage/quota indicator.
- Search box with results view.
- "Shared with me" section.

Not included (per non-goals): previews, drag-and-drop upload, progress bars beyond the browser's
native behavior.

### 5.9 Administration (extension of existing platform)

- Existing: user creation, activation/deactivation, roles.
- Added by this product: set/change a user's quota, view per-user storage usage, configure
  service-wide defaults (default quota, max file size, version retention N, trash retention
  period).

## 6. Later phases (post-MVP backlog, in rough priority order)

1. File previews and richer upload UX (drag-and-drop, progress) in the web UI.
2. Desktop sync client.
3. Content search inside documents.
4. Storage efficiency work (deduplication, compression) — invisible to users, product benefit is
   more effective space.
5. Mobile-friendly UI or native mobile apps.
6. E2EE option.

## 7. Constraints and assumptions

- **Scale target:** tens of users, gigabytes to low terabytes of data, single server, single
  region. Architecture should not preclude growth but must not pay for it up front.
- **Deployment:** self-hosted via the existing Docker Compose path; a technically capable person
  can bring the service up with one command and the README.
- **Platform:** builds on the existing authenticated API platform (accounts, roles, sessions) —
  storage features assume an authenticated user context exists.
- **Clients:** modern evergreen browsers and standard HTTP tooling. No legacy browser support.

## 8. Success criteria

v1 is successful when:

1. A new user can sign in, upload a file, organize it into folders, and download it again — first
   try, without documentation.
2. A shared link opened in a private browser window (no account) downloads the intended file, and
   stops working the moment the owner revokes it.
3. Overwriting a file 5 times leaves every prior version listed and restorable; the 6th overwrite
   drops only the oldest.
4. A deleted file is restorable from trash to its original place within the retention window, and
   is genuinely gone (space reclaimed) after it.
5. An upload exceeding quota or max file size fails with a message that states the limit; a user's
   displayed usage matches what they actually store, versions and trash included.
6. Search returns a known file by partial name among thousands of stored files, fast enough to
   feel instant in the UI.
7. The operator can run the whole service from the existing Compose setup and restore user data
   from a plain backup of the server.

## 9. Decision log

Product-level decisions made during PRD review (2026-07-19), recorded here so the reasoning
survives:

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Deletion model | Minimal trash in MVP: 30-day soft delete + restore | Permanent single-click deletes were the product's biggest data-loss risk; a bounded trash removes it at modest scope cost. |
| 2 | Editor delete rights | Editors **can** delete within shared scope | Safe once trash exists — editor deletions land in the owner's trash and are undoable; matches collaborative-folder expectations. |
| 3 | Version retention default | N = 5 | Leaner disk footprint for self-hosted deployments; admin-configurable anyway. |
| 4 | Folder public links | Expose the whole tree, including future additions | Matches Dropbox/Drive behavior users already understand. |
| 5 | MVP scope | Files/folders + both sharing modes + versioning + trash + quotas + search + minimal web UI | Chosen during initial scoping; sharing is the largest single feature. |
| 6 | Access modes | REST API + web UI; no sync clients in v1 | Sync is the highest-complexity feature in this product class; deferred deliberately. |

## 10. Glossary

| Term | Meaning |
|---|---|
| Owner | The user in whose hierarchy an item lives; always retains full control. |
| Item | A file or folder. |
| Share | A grant of access to an item — either a public link or a user-to-user grant. |
| Version | The content of a file as it existed before an overwrite; bounded by retention. |
| Trash | Per-user holding area for deleted items; restorable for the retention period. |
| Quota | Per-user cap on total stored bytes — current files, versions, and trash included. |
| Retention (N) | Number of versions kept per file, service-wide setting. |
