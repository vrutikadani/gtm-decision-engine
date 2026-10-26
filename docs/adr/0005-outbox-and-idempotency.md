# ADR 0005: Outbox pattern, with search-before-create on every side effect

**Status:** accepted

## Context
The two dangerous moments are "Slack timed out: did the message post?" and "the CRM write succeeded, then the worker died before saving state".

## Decision
- The decision, its state transition and its outbox rows are written in **one transaction** (`Engine._persist`).
- A worker (`gde/delivery/worker.py`) performs the outbox rows. It can crash at any point; the row stays pending and is replayed.
- Replays are safe because each side effect looks for itself first:
  - **Slack:** every message carries `metadata.gde_key`. Before posting, the worker searches the channel for it (Slack's `chat.postMessage` has no idempotency key).
  - **CRM:** every created record carries a `gde_key` property. `upsert` searches before creating.
- Retries are capped by `delivery_max_attempts`. After that the run goes to `DELIVERY_FAILED` and shows on the reliability panel.

## Consequences
- At most one message and one CRM record per decision, even across crashes. Tests and failure injections cover each case.
- Cost: one extra read per side effect, and a worker to operate.

