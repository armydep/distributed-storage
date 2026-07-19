# ADR-0009: React SPA (TypeScript + Vite) as the web UI

**Status:** Accepted · 2026-07-19

## Context

The PRD requires a minimal-but-complete web file manager (browse, upload, share dialogs, versions,
trash, search). The platform is API-first with JWT auth and strict CORS already built.

## Decision

A standalone single-page application: React with TypeScript, built with Vite, deployed as a static
build from its own container/origin. It consumes the REST API exclusively — no server-side
rendering, no template coupling to FastAPI.

## Alternatives considered

- **Server-rendered Jinja2 + htmx** — one deployable, no JS toolchain, and the recommended fit
  for a minimal file manager; rejected by the owner in favor of a clean API-first separation and
  a higher UX ceiling for later phases (previews, drag-drop).
- **Vue / Svelte** — equally viable; React chosen for the largest ecosystem and tooling pool.

## Consequences

- The API remains the single product interface — the SPA is just its first client, which keeps
  the door open for future clients (sync, mobile) honestly.
- A second project to build, lint, test, and version inside the repo; a JS toolchain joins CI.
- Browser auth and cross-origin behavior become real design areas (settled in ADR-0011/0012).
