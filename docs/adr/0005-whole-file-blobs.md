# ADR-0005: Whole-file blobs, no chunking in v1

**Status:** Accepted · 2026-07-19

## Context

Dropbox-class systems split files into fixed-size chunks to enable delta sync and block-level
dedup. Chunking complicates every flow: upload assembly, download streaming, quota math, and
garbage collection of orphaned chunks. The PRD explicitly defers sync clients (non-goal in v1).

## Decision

Each file version is stored as exactly one object. No chunking.

## Alternatives considered

- **Fixed-size chunks from day one** — pays sync's infrastructure cost years before sync exists,
  and taxes every v1 flow for a feature the PRD excludes.

## Consequences

- Upload, download, finalize, refcounting, and GC all operate on one object per version — the
  simplest correct model.
- Whole-file dedup only (identical files dedup; near-identical don't). Accepted at v1 scale.
- If sync arrives (PRD later-phase), chunking becomes a new ADR superseding this one; the
  content-addressed scheme (ADR-0004) extends to chunks without relocating existing data.
