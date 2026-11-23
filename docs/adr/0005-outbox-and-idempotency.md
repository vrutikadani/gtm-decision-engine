# ADR 0005: Outbox pattern, with search-before-create on every side effect

**Status:** accepted (amended: per-row failure handling, attempt cap and dead letters for every row kind)

## Context
The two dangerous moments are "Slack timed out: did the message post?" and "the CRM write succeeded, then the worker died before saving state".

A third one was found in an audit: a CRM 504 on a write-back. The worker had no error handling for CRM rows. The error escaped after the run was already committed `ACCEPTED`, the API returned 500, and the pending row raised again on every later pass. Because the worker processes rows in order, an unrelated signal's Slack card behind it never went out.

## Decision
- The decision, its state transition and its outbox rows are written in **one transaction** (`Engine._persist`).
- A worker (`gde/delivery/worker.py`) performs the outbox rows. It can crash at any point; the row stays pending and is replayed.
- Replays are safe because each side effect looks for itself first:
  - **Slack post:** every message carries `metadata.gde_key`. Before posting, the worker searches the channel for it (Slack's `chat.postMessage` has no idempotency key).
  - **Slack retraction:** `chat.update` sets the same content again on replay, so it is safe without a lookup.
  - **CRM:** every created record carries a `gde_key` property. `upsert` and `revert` search before creating.
- **Failures are handled per row, the same way for every kind** (`slack`, `crm_writeback`, `crm_compensate`, `slack_retract`). `worker.process` catches an adapter error for that row only and calls `_fail`:
  - `attempts` goes up by one and the error is saved in `last_error`
  - the row stays `pending` until `attempts` reaches `delivery_max_attempts` (3)
  - then it becomes `dead`. Nothing retries a dead row.
  - a dead Slack post moves the run to `DELIVERY_FAILED`. A dead CRM or retraction row does not change the run state (the seller really did accept or correct). It sets a run flag instead: `WRITEBACK_FAILED`, `COMPENSATION_FAILED` or `RETRACTION_FAILED`.
  - `GET /reliability` returns `dead_letters` and `writeback_failed`; the reliability panel and the inspector show them.
- `WorkerCrash` is not caught per row. It stands in for the process dying, so the pass stops, as it would.
- Retries happen across passes of one `process()` call. Backoff is not modeled.

## Consequences
- At most one message and one CRM record per decision, even across crashes and retries. Tests: `tests/test_reliability.py`, `tests/test_adversarial.py`, `tests/test_outbox_and_ordering.py` (`test_crm_failure_does_not_block_unrelated_slack_card`, `test_crm_writeback_dead_letters_after_max_attempts`, `test_crm_transient_failure_is_retried_and_written_exactly_once`).
- Cost: one extra read per side effect, and a worker to operate.
- Not built: re-driving a dead row from the UI, real backoff with jitter, and alerting on dead letters. Today a person sees them on the reliability panel.
