# ADR-0001: Record architecture decisions as ADRs

**Status:** Accepted · 2026-07-19

## Context

This project is developed step-by-step with the owner making every significant implementation
choice. Those choices need to survive as more than chat history: future contributors (human or AI)
must be able to see *what* was decided, *what else was on the table*, and *why* — especially when a
later phase (e.g. sync) revisits an earlier decision.

## Decision

Every significant architectural or technology decision gets one short ADR in `docs/adr/`, numbered
sequentially, with sections: Status, Context, Decision, Alternatives considered, Consequences.
ADRs are immutable once accepted; changing course means a new ADR that supersedes the old one
(both are kept, cross-referenced).

## Consequences

- Decisions are reviewable in PRs like code and discoverable next to the code they govern.
- The cost is small (one short file per decision); the discipline is the point.
