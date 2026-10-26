# Code walkthrough map

Use this map when someone says "show me the code". Line numbers are approximate; jump by function name.

## Product concept → file

| Concept | File | Look at |
|---|---|---|
| Webhook in, decision out | `gde/decisions/engine.py` | `Engine.ingest` → `evaluate` → `_decide` → `_persist` |
| Vendor normalization (two payload shapes) | `gde/providers/job_change.py` | `normalize`, `subject_keys`, `move_key` |
| Duplicate and cross-vendor dedupe | `gde/decisions/engine.py` | `_ingest`; UNIQUE constraint in `gde/store.py` |
| Champion identity resolution | `gde/champions/resolution.py` | `resolve`: candidates, constraints, noisy-OR, margin |
| Champion evidence | `gde/champions/validation.py` | `validate`: 2+ types, 1 first-party, 3-year lookback |
| Source precedence (truth layer) | `gde/context/truth.py` + `gde/config/precedence.json` | `account_context`; CRM down raises `ContextUnavailable` |
| Account qualification | `gde/accounts/qualification.py` | `qualify` |
| Approved plays | `gde/config/plays.json` + `gde/plays/registry.py` | `evaluate`: every play, with reasons |
| Every threshold | `gde/config/thresholds.json` | identity weights, freshness, cooldowns, rep cap |
| Decision trace | `gde/decisions/engine.py` | `Trace.add`, `Trace.finish` |
| Seller card (Slack surface) | `gde/decisions/engine.py` | `_surface` (opener validation inside) |
| Workflow states | `gde/workflows/state.py` | `TRANSITIONS`, `transition` |
| Outbox worker, retries, idempotency | `gde/delivery/worker.py` | `deliver_slack`, `crm_writeback`, `crm_compensate`, `process` |
| Slack adapter | `gde/delivery/slack.py` | `find_by_metadata`, `post` |
| CRM adapter | `gde/providers/crm.py` | `upsert` (search-before-create), `revert` |
| Seller feedback | `gde/feedback/service.py` | `submit`, `COMPENSATE`, `wake_snoozed` |
| Human review queue | `gde/service.py` | `reviews`, `resolve_review` |
| GTM briefs | `gde/briefs/service.py` | `quarantine`, `validate_mention`, `build` |
| LLM abstraction | `gde/llm/provider.py` | `MockProvider`, `AnthropicProvider`, `FallbackProvider` |
| Transactions | `gde/store.py` | `Store.tx`, `after_rollback` |
| System inspector data | `gde/service.py` | `inspect` |
| Reliability panel data | `gde/service.py` | `reliability` |
| HTTP API (`/docs`) | `gde/api.py` | routes under `/api` |
| Browser demo router | `gde/bridge.py` | `ROUTES`, `handle`, `dispatch` |
| Failure injection (demo only) | `gde/faults.py`, `gde/demo/failures.py` | `Faults.arm` raises outside demo |
| Scenarios | `gde/demo/scenarios.py` | `SCENARIOS`, `run`, `followup` |
| Hardest failure, before/after | `gde/demo/hardest_failure.py` | `BEFORE` is a capture from the pre-fix commit |
| Synthetic world | `gde/fixtures/world.json` | `_why` on each record |
| Demo UI | `web/app.js` | `call()` is the only transport; `boot()` picks local API or Pyodide |

## Tests and evals

| What | File |
|---|---|
| Scenarios 1 to 5 end to end | `tests/test_scenarios.py` |
| Duplicates, timeouts, retries, crashes, invalid transitions | `tests/test_reliability.py` |
| Tests written to break it, plus regressions for the hardest failure | `tests/test_adversarial.py` |
| Hardening added after the mock interview | `tests/test_readiness.py` |
| HTTP and browser route parity; manifest freshness | `tests/test_api.py` |
| Identity / decision / brief evaluation | `evals/run_eval.py` |
| Threshold sweep | `evals/threshold_sweep.py` |

## Three code tours worth rehearsing

1. **"Why did this go to review?"** Open `resolve()` in `champions/resolution.py`. Show the `REVIEW` branch: the best score is below 0.80, or two candidates are within 0.20 of each other.
2. **"How do you prevent duplicates?"** In order:
   - `_ingest` (UNIQUE on provider + event id, then `move_key` across vendors)
   - `deliver_slack` (metadata lookup before every post)
   - `SimulatedCRM.upsert` (search on `gde_key` before create)
3. **"What happens after the seller corrects it?"** Open `feedback/service.py` `submit`, the `correct` branch:
   - cancel pending writes
   - queue compensation
   - exclusions under every subject key
   - RevOps task
   - rerun
