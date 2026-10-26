# ADR 0007: SQL (SQLite here) with state tables and an audit log, not an event store

**Status:** accepted

## Decision
One SQLite database (`gde/store.py`): reference data, runs with a current state, a transitions table, decisions with their trace as JSON, the outbox, feedback, and an append-only audit table. `Store.tx()` gives all-or-nothing writes. The same code runs in memory in the browser.

## Consequences
- Simple to reason about and to demo; the transitions and audit tables give most of the history an event store would.
- Cost: no replay-by-rebuilding-projections, and SQLite serializes writes. In production this would be Postgres with the same tables and row-level locking on runs.

## Interview questions this decision may trigger
- Why not an event store?
- What changes at 10M events? (Postgres, partitioned audit and decisions, a queue in front of ingest, workers per side-effect type.)
- How do you keep the trace from bloating the database? (Today the trace is JSON on the decision row. At scale, move it to object storage with a pointer and keep a summary.)
