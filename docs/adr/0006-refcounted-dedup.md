# ADR-0006: Reference-counted deduplication in v1

**Status:** Accepted · 2026-07-19

## Context

Content-addressing (ADR-0004) means identical content maps to the same object key. The choice is
whether to exploit that: one blob shared by many versions/users (needs reference counting before
any delete), or one blob per version (no sharing, simple deletes, duplicated bytes).

## Decision

Deduplicate. A blob row in PostgreSQL tracks each unique content hash with a reference count;
every file version holds a reference. Refcount transitions happen in the same transaction as the
version change that causes them. Only the worker deletes content objects, and only at refcount
zero (plus a GC safety window).

Quota remains **logical**: every owner is charged full size for every version they hold,
regardless of physical sharing — dedup is an operator-side saving, invisible to users.

## Alternatives considered

- **No dedup in v1** — simplest deletes (blob dies with its version), but versions that share
  content (e.g. restore-old-version) would still need either copying bytes or refcounts anyway,
  and retrofitting dedup later means a data migration.

## Consequences

- Identical files across users/versions are stored once; restore never copies bytes.
- Refcount correctness becomes a data-loss-critical invariant — deletion code ships only with
  tests covering the transitions, and orphan-GC reconciles rather than trusts.
