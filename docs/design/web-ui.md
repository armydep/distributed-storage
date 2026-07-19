# Design: Web UI (React SPA)

| | |
|---|---|
| Status | Approved |
| Feature | Web UI (PRD §5.8) — final design doc; implementation follows this one |
| ADRs | [0009 React SPA](../adr/0009-react-spa-frontend.md), [0011 separate origins](../adr/0011-separate-origins-cors.md), [0012 httpOnly cookies](../adr/0012-httponly-cookie-session.md) |
| Depends on | every prior design doc — this is the client for all of them |
| Last updated | 2026-07-19 |

Structure, data layer, and screen inventory for the SPA. No new backend behavior — every
endpoint referenced here is already specified in an earlier doc.

## 1. Decisions this doc is built on

| Decision | Choice (owner) | Rejected |
|---|---|---|
| Data fetching/caching | **Hand-rolled `fetch` + `useState`/hooks** — no query library | TanStack Query (recommended: built-in polling/caching/dedup, would have made §4 mostly unnecessary) |
| Multi-file upload concurrency | **Sequential** — one active upload at a time | Parallel (faster for many files, more simultaneous worker load and client state) |
| UI components | **Hand-rolled, minimal CSS** — no component library | Lightweight library e.g. Radix (recommended: large time savings on the several modal flows) |
| Background status updates | **Global background polling** — survives navigation | Component-local (simpler, but a finished upload can go unnoticed off-screen) |

**Direct consequence of the first three rejections together:** without a query library or
component library, this doc has to specify the patterns those would have provided —
§4 (data layer) and §5 (activity/polling) exist specifically to fill that gap coherently, rather
than leaving each screen to improvise caching and polling independently.

Two implementation details are fixed here as ordinary defaults, not owner decisions (low-stakes,
standard, reversible without touching any other design doc): **React Router v6** for
navigation/deep-linking, and **Vitest + React Testing Library** for tests (the standard Vite
pairing). Flagged so it's clear these weren't skipped, just not worth a question.

## 2. Project structure

```
web/                          # standalone project (ADR-0009) — own package.json, own container
├── src/
│   ├── main.tsx
│   ├── App.tsx                # router root + AuthProvider + ActivityProvider + ToastProvider
│   ├── api/
│   │   ├── client.ts           # fetch wrapper: credentials, CSRF header, refresh-on-401 (§3)
│   │   ├── types.ts            # mirrors backend schemas (hand-kept in sync; see §7)
│   │   └── {auth,folders,files,trash,shares,links,search,admin}.ts   # one module per resource
│   ├── auth/
│   │   ├── AuthContext.tsx     # session state: 'loading' | user | null
│   │   └── useAuth.ts
│   ├── activity/                # global background polling (§5)
│   │   ├── ActivityContext.tsx
│   │   ├── useActivity.ts
│   │   └── dataBus.ts           # minimal pub-sub for cross-view refresh (§5.3)
│   ├── routes/
│   │   ├── LoginPage.tsx
│   │   ├── FilesPage.tsx        # folder browser, param: folderId
│   │   ├── SharedWithMePage.tsx
│   │   ├── TrashPage.tsx
│   │   ├── SearchPage.tsx
│   │   └── AdminPage.tsx        # user list + quota edit; read-only service settings display
│   ├── components/
│   │   ├── Breadcrumbs.tsx  ItemTable.tsx  UploadButton.tsx  ActivityTray.tsx
│   │   ├── ShareDialog.tsx  VersionListDialog.tsx  ConfirmDialog.tsx
│   │   ├── QuotaIndicator.tsx  Toast.tsx
│   └── styles/                  # plain CSS, one file per component (co-located)
├── index.html  vite.config.ts  package.json  tsconfig.json
```

## 3. API client (`api/client.ts`)

One shared wrapper implementing exactly what `auth-cookies.md` specifies, so no individual screen
re-implements auth mechanics:

1. Every request: `credentials: 'include'` (send `ds_access`/`ds_refresh` cookies cross-origin).
2. Every mutating request (POST/PUT/PATCH/DELETE): header `X-CSRF-Protection: 1` attached
   automatically — screens never think about this.
3. On any `401`: trigger `refresh()` — but **single-flight**: a module-level `refreshPromise`
   variable is set on the first 401, and any concurrent request hitting a 401 while it's pending
   awaits the *same* promise instead of calling `/auth/refresh` again (per `auth-cookies.md` §7 —
   parallel refresh calls would trip the platform's own replay detection). On refresh success,
   retry the original request once; on refresh failure, clear auth state and route to `/login`.
4. Responses are parsed against the standard error envelope (`{"error": {code, message, ...}}`);
   `client.ts` throws a typed `ApiError { code, message, status }` so callers can branch on
   `error.code` (e.g. `QUOTA_EXCEEDED`) without string-matching messages.
5. All request/response typing lives in `api/types.ts`, hand-kept in sync with the backend
   schemas (no codegen in v1 — see §7 for why, and when to revisit).

## 4. Data layer pattern (replacing what a query library would give)

Every resource module (`api/folders.ts` etc.) exports plain async functions
(`listFolder(id)`, `renameFile(id, name)`, …) calling `client.ts`. Screens consume them through a
small shared hook shape, hand-rolled once and reused everywhere:

```ts
function useResource<T>(fetcher: () => Promise<T>, deps: unknown[]) {
  // returns { data, error, loading, refetch }
  // re-runs fetcher when deps change; refetch is exposed for manual invalidation
}
```

This is the entire "caching layer": no cross-component cache, no automatic background
refetching except where §5 explicitly drives it. A screen that needs fresh data after a mutation
calls `refetch()` itself (e.g. `FilesPage` refetches its folder listing after a successful
rename). This is a deliberate simplicity trade-off — acceptable because the app has few
screens and modest concurrent-editing needs (single self-hosting household, per the PRD's target
user), not because it scales indefinitely; a query library remains the natural upgrade if that
stops being true.

## 5. Activity system (global background polling)

The one piece of real cross-view state, because the owner chose global-not-local polling.

### 5.1 `ActivityContext`

Holds `Map<id, ActiveTask>` where `ActiveTask = { id, kind: 'upload' | 'purge', label, status }`.
Exposes `register(task)` (called right after an upload `complete` or a trash `DELETE` returns its
202) and the current task list for `ActivityTray` to render.

### 5.2 Polling loop

One `setInterval` (2 s, matching the cadence already fixed in `upload-download.md` §2.4 and
`trash-and-jobs.md` §2.4) owned by the provider, not per-component: on each tick, poll every task
currently `processing`. On a task reaching `done`/`failed`: update its status (shown briefly in
the tray, e.g. "cat.jpg uploaded" for a few seconds, then auto-dismiss), stop polling it, and —

### 5.3 Cross-view refresh (`dataBus`)

A minimal pub-sub, not a cache: `dataBus.emit('folder', folderId)` /
`dataBus.on('folder', folderId, callback)`. When a task in §5.2 completes, the activity provider
emits for the affected folder (upload's target folder; purge's... nothing, since purge only
touches trash — see below). `FilesPage`, mounted or not, subscribes for its current `folderId`
and calls its `refetch()` if notified. This is intentionally narrow: it exists only to solve
"upload finished while I was looking at a different folder, then I navigate back — is it there?"
— not a general cache-invalidation system. `TrashPage` similarly subscribes to a `'trash'` topic,
emitted when any purge task completes.

### 5.4 What this buys, concretely

Alice uploads `report.pdf` into `Work/`, immediately clicks into `Photos/` to check something.
The tray shows "report.pdf processing…" the whole time; when it flips to "done," if she later
opens `Work/` its listing is already correct (either freshly fetched because it wasn't cached at
all — first visit — or refetched because `FilesPage` was subscribed and got the `dataBus` ping if
still mounted). Either way she never has to manually refresh.

## 6. Screens (mapped to PRD §5.8)

| Screen | Route | Backend calls | Notes |
|---|---|---|---|
| Login | `/login` | `POST /auth/login?use_cookies=true` | On success → `GET /users/me` → route to `/files` |
| File browser | `/files/:folderId?` | list (§storage-model), `POST /files/uploads*` (§upload-download), rename/move/delete | Breadcrumbs from ancestor chain; folders-first name-order listing, per `storage-model.md` §4 |
| Shared with me | `/shared` | `GET /shared-with-me` (§sharing) | Opening a shared folder routes into `/files/:folderId` — same browser, permission-gated per `sharing.md` §5.7 |
| Trash | `/trash` | `GET /trash`, restore, `DELETE /trash/*` (§trash-and-jobs) | Restore/trash-flag actions are synchronous (instant UI update); permanent delete goes through the activity tray (§5) |
| Search | `/search?q=` | `GET /search` (§quota-search-admin) | Debounced input (300 ms) before firing |
| Admin | `/admin` | user list + `PATCH /users/{id}` (quota), `GET` effective settings | Settings shown read-only per `quota-search-admin.md` §1's flagged scope reduction |
| (all) | — | `GET /users/me/usage` | `QuotaIndicator`, persistent in the app shell, refetched on any upload/purge completion via `dataBus` |

Modal flows (`ShareDialog`, `VersionListDialog`, `ConfirmDialog` for delete/empty-trash/restore-
conflict-none-needed-since-auto-rename) are dialogs over the file browser, not routes — closing
one just calls the relevant screen's `refetch()`.

## 7. Type sync (hand-kept, not generated)

`api/types.ts` mirrors the backend's Pydantic schemas by hand. No OpenAPI-codegen step in v1 —
the API surface is still being built alongside this UI, and a codegen pipeline is friction while
both sides are moving. Revisit (generate types from the API's existing `/api/v1/openapi.json`)
once the backend for a given feature has shipped and stabilized; not before.

## 8. Error and empty states

- `ApiError.code` from `client.ts` (§3) maps to specific inline messages where it matters
  (`QUOTA_EXCEEDED` shows the limit, per `upload-download.md`'s error catalog); anything
  unmapped falls back to a generic toast with `error.message`.
- Every list screen has an explicit empty state (empty folder, empty trash, no search results,
  nothing shared) — not just a blank area.

## 9. Test plan

- `client.ts`: CSRF header present on mutating requests only; single-flight refresh (two
  concurrent 401s trigger exactly one `/auth/refresh` call — mock-timer test); refresh failure
  routes to login.
- `useResource`: refetch updates state; error surfaces without throwing past the hook.
- Activity system: a registered task polls until terminal, then stops; `dataBus` emission reaches
  a subscribed `FilesPage` instance and not an unrelated one; unmount during polling doesn't leak
  the interval (cleanup test).
- Screen-level (React Testing Library): login → files redirect; upload → tray shows
  processing → done → item appears; rename/move/delete round-trip against a mocked API; trash
  restore and permanent-delete-via-tray; share dialog CRUD; search debounce fires once per pause,
  not per keystroke.
- No end-to-end/browser tests specified yet — added once there's a running backend to point them
  at (this doc precedes implementation, per the process).

## 10. Out of scope

Previews, drag-and-drop, upload progress bars beyond the activity tray's coarse
processing/done state (all explicit PRD non-goals, §5.8). Offline support. Multi-tab live sync
beyond what auth-cookies.md's session handling already does (a second tab simply calls its own
`refetch()`s on its own schedule; no cross-tab messaging in v1).
