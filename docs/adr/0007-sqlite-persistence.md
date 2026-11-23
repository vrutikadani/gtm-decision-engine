# ADR 0007: SQL (SQLite here) with state tables and an audit log, not an event store

**Status:** accepted (amended: a file database now survives restarts; recovery sweeper added)

## Decision
One SQLite database (`gde/store.py`): reference data, runs with a current state, a transitions table, decisions with their trace as JSON, the outbox, feedback, per-person event watermarks, and an append-only audit table. `Store.tx()` gives all-or-nothing writes.

Where it lives:

- **In memory** by default, in tests and in the browser demo.
- **A file** when `GDE_DB=path.db` is set for the local server.

What survives a restart (file database only):

- Everything in the database. Reference data is seeded only into an empty database. Only `POST /demo/reset` wipes it. (Before this change, `Service.__init__` called reset and deleted every table on every start.)
- On startup against an existing file, `Service.recover()` runs a sweeper. A run is committed `EVALUATING` before the engine decides, and the decision is committed with the next state in one transaction. So a run still `EVALUATING` at startup was interrupted between the two. The sweeper re-evaluates each such run once, then drains the outbox.

What does not survive a restart:

- The simulated Slack and CRM keep their messages and records in Python memory. They stand in for external systems, which would keep their own state.
- The demo clock restarts at `demo_now`.

## Consequences
- Simple to reason about and to demo; the transitions and audit tables give most of the history an event store would.
- Recovery is at-least-once evaluation with exactly-once commit: if the process dies again during a sweep, the run is still `EVALUATING` and the next start retries it. A decision is only ever written once per evaluation because `_persist` is one transaction. Test: `tests/test_outbox_and_ordering.py::test_file_db_survives_restart_and_stuck_run_is_recovered_once`.
- The sweeper runs only at startup. It assumes one process: a second process sweeping while the first is mid-evaluation would evaluate the same run twice. In production the sweeper would claim runs with a lease (`SELECT ... FOR UPDATE SKIP LOCKED`).
- One connection, serialized by a lock in `api.py`. No WAL, no schema migrations: a schema change needs a fresh file.
- Cost: no replay-by-rebuilding-projections, and SQLite serializes writes. In production this would be Postgres with the same tables and row-level locking on runs.
