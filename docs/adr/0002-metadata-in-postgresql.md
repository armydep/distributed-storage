# ADR-0002: All metadata lives in the existing PostgreSQL

**Status:** Accepted · 2026-07-19

## Context

The platform already runs PostgreSQL for accounts, auth, and refresh tokens. The storage product
adds folder hierarchy, files, versions, shares, public links, trash state, quotas, blob reference
counts, and upload sessions — all relational, transactional data.

## Decision

One PostgreSQL instance is the single source of truth for **all** metadata. File *bytes* never go
in the database (see ADR-0003); everything else does. No second metadata store.

## Alternatives considered

- **Separate metadata DB per module** — premature; the modular monolith shares one DB by design,
  with module boundaries enforced at the repository layer, not the connection string.
- **Document store for hierarchy** — folder trees, shares, and refcounts are exactly the
  relational/transactional shape; a document store would trade integrity for nothing at this scale.

## Consequences

- Cross-feature invariants (quota vs versions vs trash, refcounts vs versions) are enforceable in
  single transactions.
- Backup story stays "one DB dump + one bucket" (see ARCHITECTURE §6).
- The DB becomes the scaling bottleneck far later than the PRD's scale target requires.
