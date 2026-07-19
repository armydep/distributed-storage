# ADR-0004: Content-addressed blob layout

**Status:** Accepted · 2026-07-19

## Context

Blobs need names in the object store. The user-visible hierarchy (folders, filenames) changes
constantly — renames, moves, versions — while file *content* is immutable once written.

## Decision

Finalized objects are stored under their content hash (`content/<hash>`). The object store knows
nothing about users, folders, or filenames; PostgreSQL maps hierarchy → blob.

## Alternatives considered

- **Mirror the user hierarchy in object keys** — human-browsable in the bucket, but every
  rename/move becomes a physical object operation, versioning needs a parallel naming scheme, and
  dedup is impossible.
- **Opaque random keys (UUID per version)** — decouples hierarchy like content-addressing does,
  but forfeits dedup (ADR-0006) and the integrity property below.

## Consequences

- Rename/move/restore are pure metadata transactions — instant, atomic, at any file size.
- The stored hash doubles as an end-to-end integrity check on every finalize.
- Deduplication (ADR-0006) falls out naturally; chunked storage (rejected for now, ADR-0005) would
  slot into the same scheme if sync ever demands it.
- Blobs are immutable and shared, so deletion requires reference counting — the price paid in
  ADR-0006.
