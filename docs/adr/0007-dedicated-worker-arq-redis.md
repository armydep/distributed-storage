# ADR-0007: Dedicated worker service on arq + Redis

**Status:** Accepted · 2026-07-19

## Context

The product needs background execution: queued upload finalization (ADR-0010) and periodic jobs
(trash purge, version pruning, staging sweep, orphan-blob GC). The question is where that work
runs and what queues it.

## Decision

A dedicated worker service — the same Python codebase in a second container — consuming jobs via
**arq** backed by **Redis**. Redis is queue-only: not a cache, not a session store, and treated as
losable (every queued action is idempotent and backstopped by a periodic sweep).

## Alternatives considered

- **In-process scheduler in the API** — zero new containers and the recommended minimum; rejected
  by the owner in favor of real process isolation between request serving and byte-heavy
  finalize/GC work.
- **Postgres-backed queue (Procrastinate)** — no new infrastructure, transactional enqueue;
  rejected in favor of the conventional Redis queue model.
- **Celery** — mature but sync-first and operationally heaviest; arq is async-native, matching
  the codebase.

## Consequences

- Finalization and GC load never competes with API request latency.
- Redis joins the stack as a stateful-but-losable service; losing it loses promptness, not data.
- The worker importing the same services/repositories keeps one implementation of every business
  rule.
