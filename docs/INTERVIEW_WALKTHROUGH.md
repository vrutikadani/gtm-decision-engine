# Interview walkthrough

A timed script for showing this repo. Every claim points at code or a test.

## 30 seconds: context

- A former champion changes jobs. That is one of the best pipeline signals in B2B sales.
- Most teams act on it badly. They message the wrong person, ping a rep who already has a deal open, or post twice.
- This repo is a synthetic reference build. It decides whether to act, tells one seller with evidence, and learns from their feedback.
- Code decides. The model only labels, extracts and drafts. A person decides the ambiguous cases.

## 90 seconds: architecture

Picture diagram A (`docs/diagrams/a-system.svg`).

1. A vendor webhook arrives. It is normalized into one `JobChange` record.
2. Dedupe drops repeats: the same event id, or the same move from a second vendor.
3. The decision engine runs ordered rules. Each rule writes a trace entry.
4. The decision, its state change and its side effects are written in one SQLite transaction. Side effects go to an outbox table.
5. A worker performs the outbox rows: post a Slack card, write to the CRM, undo CRM writes, edit a card.
6. Seller feedback changes state and future decisions.

What is real and what is not:

- The CRM, Slack and enrichment are simulated adapters.
- Accounts, people, evidence and conversations are fixtures in `gde/fixtures/world.json`.
- The same `gde` package runs behind FastAPI and in the browser through Pyodide.

## 5 minutes: one trace

### Webhook to Slack card

1. `gde/api.py:job_change` calls `gde/bridge.py:handle`, then `gde/service.py:Service.job_change`.
2. `gde/decisions/engine.py:Engine._ingest`
   - `providers/job_change.py:normalize` maps the vendor payload.
   - One transaction inserts the signal and a run in state `RECEIVED`.
   - A UNIQUE key on (provider, event id) stops a replayed webhook.
   - The same move from another vendor within 14 days becomes `DUPLICATE`.
3. `Engine.evaluate` commits the run as `EVALUATING`. Then `Engine._decide` runs the rules:
   - freshness: 30 days at most
   - identity: `champions/resolution.py:resolve` returns MATCH, REVIEW or NO_MATCH
   - event order: a per-person watermark on `detected_at`. An older move is recorded but suppressed.
   - champion evidence: `champions/validation.py:validate`
   - account context: `context/truth.py:account_context`. CRM down means HOLD, not a guess.
   - qualification, seller suppressions, cooldowns
   - conversation intent: the model labels each utterance; `engine.py:validate_intent` drops unknown labels and clamps confidence
   - play eligibility: `plays/registry.py:evaluate`, then the rep daily cap
4. `Engine._persist`
   - `Engine._draft_opener` calls the model first, outside any transaction, and validates the sentence.
   - One transaction writes the decision, trace, model calls, the next state, the watermark and an outbox row.
5. `delivery/worker.py:process` runs `deliver_slack`.
   - It searches the channel for the decision id in message metadata before posting.
   - So a timeout after a successful post never makes a second card.

### Accept to CRM write-back

1. `feedback/service.py:submit` moves the run to `ACCEPTED` and queues a `crm_writeback` row.
2. `worker.py:crm_writeback` calls `providers/crm.py:SimulatedCRM.upsert`. It searches by `gde_key` before creating.
3. If the CRM fails, `worker.py:_fail` counts the attempt. After 3 the row is `dead` and the run is flagged `WRITEBACK_FAILED`.
4. Other rows keep moving. The reliability panel lists dead letters (`service.py:reliability`).

### Correction

1. `submit(..., "correct", reason="wrong_person")`:
   - cancels a pending write-back
   - queues `crm_compensate`, which reverts what the CRM actually holds
   - queues `slack_retract`, which edits the posted card to say it was withdrawn
   - stores an identity exclusion under every subject key
   - re-evaluates the same signal without the wrong person
2. Next time, even a second vendor with no profile URL does not bring the wrong person back.

## Mapping to Data → Orchestration → Agents → Execution

| Layer | Here | Files |
|---|---|---|
| Data | Fixtures, vendor normalization, field precedence, champion evidence | `fixtures/world.json`, `providers/job_change.py`, `context/truth.py` |
| Orchestration | Run state machine, transactions, outbox, startup sweeper | `workflows/state.py`, `store.py`, `delivery/worker.py`, `service.py:recover` |
| Agents | Three bounded model jobs, each validated by code | `llm/provider.py`, `engine.py:validate_intent`, `engine.py:_draft_opener`, `briefs/service.py:validate_mention` |
| Execution | Slack card, CRM write-back, compensation, card edit | `delivery/slack.py`, `providers/crm.py`, `worker.py` handlers |

The "agent" layer is thin on purpose. The model never picks a person, a play or an owner, and never writes.

## Why an outbox and a sweeper, not a durable-orchestration framework

- The workflow is short: decide, then one to three side effects. It has no long waits and no fan-out.
- The hard part is idempotent side effects. A framework does not solve that. Slack has no idempotency key; you still need search-before-post.
- One table and one worker are easy to read in an interview and easy to test with injected faults.
- No new dependency, so the same code still runs in the browser.
- I would switch to a durable engine (Temporal, Step Functions) when runs wait days on humans, when many workers compete, or when retries need timers and backoff. The sweeper here is single-process, and backoff is not modeled.

## 5 hard follow-ups

**1. "What if the CRM returns 504 on accept?"**
The run stays `ACCEPTED`. The row is retried, then dead-lettered and the run is flagged. Other cards still go out. Tests: `tests/test_outbox_and_ordering.py::test_crm_504_on_accept_does_not_return_500`, `::test_crm_failure_does_not_block_unrelated_slack_card`, `::test_crm_writeback_dead_letters_after_max_attempts`, `::test_crm_transient_failure_is_retried_and_written_exactly_once`.

**2. "The process dies mid-decision. What happens?"**
The run was committed `RECEIVED` at ingest and `EVALUATING` before the rules ran. The decision commits in one transaction with the next state. On restart, `Service.recover` evaluates runs left `RECEIVED` or `EVALUATING`, once. If a reviewer had already picked a person, recovery reuses that choice from `review_queue`. A file database is no longer wiped on start. Tests: `::test_file_db_survives_restart_and_stuck_run_is_recovered_once`, `::test_run_left_received_after_ingest_is_recovered_once`, `::test_review_choice_survives_crash_during_resumed_evaluation`. Limit: the sweeper is single-process; production needs leases.

**3. "What if the model returns garbage?"**
Unknown intent labels are dropped and confidence is clamped. A bad opener falls back to a template. A brief quote not found verbatim is rejected. Tests: `::test_invalid_intent_label_never_reaches_the_card`, `::test_intent_confidence_is_clamped`, `::test_anthropic_draft_opener_is_validated_by_the_engine`, `tests/test_reliability.py::test_unsupported_claim_is_rejected`.

**4. "Vendors send events out of order."**
The engine keeps the newest `detected_at` per resolved person. Vendor subject keys include the new domain, so only the person links two different moves. Tests: `::test_older_move_arriving_after_newer_one_is_suppressed`, `::test_newer_move_after_older_one_still_delivers`.

**5. "How do you know 0.80 is the right identity threshold?"**
A sweep over 24 labeled cases, now with a deterministic tune/holdout split. The tune split alone could not find the unsafe edge at 0.70; the holdout did. 13 holdout cases cannot estimate precision. Review outcomes and corrections would be the real labels. See `docs/EVALUATION.md` and `evals/threshold_sweep.py`.

## Verified vs proposed

Verified by tests in this repo (56 tests, plus `make eval`):

- dedupe, freshness, identity review, champion evidence, CRM-down hold
- Slack search-before-post, CRM search-before-create, compensation on correction
- per-row retry, cap and dead letters for every outbox kind
- file database survives restart; startup sweeper recovers stuck runs
- intent validation enforced; opener validated outside the transaction
- out-of-order suppression; posted card edited on correction

Not verified, or proposed:

- real Slack, CRM and model APIs (all simulated or stubbed; `AnthropicProvider` is tested only with a stubbed call)
- rate limits, search consistency, webhook signatures
- multi-process workers and sweepers (needs leases and row locks, e.g. Postgres)
- backoff with jitter, alerting, re-driving dead letters from the UI
- the GTM brief still calls the model inside a transaction (`service.py:build_brief`)
- precision on real data; the eval sets are small and synthetic
