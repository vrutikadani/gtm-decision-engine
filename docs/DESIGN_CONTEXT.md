# Design context

This repo decides whether a GTM signal deserves a seller's time.
The main signal is a former champion changing jobs.
It resolves who the person is, builds an account view from the CRM and enrichment, runs ordered rules, and then makes or withholds one decision.
When it acts, a seller gets one Slack card with evidence and an approved play, and their feedback changes what happens next.
In the GTM stack it covers signal intake, identity, decisioning and the seller hand-off.
It is a synthetic reference build.
The CRM, Slack and enrichment are simulated adapters.

## Where it sits in the four GTM engineering layers

The four layers come from Everett Berry's (Clay) talk "GTM Engineering: The Technical Bits."

| Layer | What this repo implements |
|---|---|
| Data | `providers/job_change.py:normalize` maps two vendor payload shapes into one `JobChange`. `champions/resolution.py:resolve` does entity resolution with explicit weights, and a close call becomes REVIEW. `context/truth.py:account_context` merges CRM and enrichment with a precedence per field (`config/precedence.json`) and records every conflict. An enrichment timeout falls back to `Enrichment.cached`, and a stale record is ignored. There is one enrichment source, not a waterfall, and no scheduled refresh. |
| Orchestration | `decisions/engine.py:Engine.evaluate` runs one signal at a time. `workflows/state.py:transition` enforces the run state machine. `store.py:Store.tx` writes the decision and its outbox rows in one transaction. `delivery/worker.py:process` performs the rows, with per-row retries and dead letters. `service.py:Service.recover` re-runs stuck runs once at startup. There is no fan-out, no timers and a single process. |
| Agents | Three bounded model jobs in `llm/provider.py`: `classify_intent`, `extract_mentions` and `draft_opener`. Code checks each one: `engine.py:validate_intent`, `briefs/service.py:validate_mention` (quote must be verbatim) and `Engine._draft_opener`. `FallbackProvider` drops to the mock if the live call fails. The model never picks a person, a play or an owner. There is no long-running agent per account. |
| Execution | `worker.py:deliver_slack` searches for the decision id before posting (`SimulatedSlack.find_by_metadata`). `worker.py:crm_writeback` goes through `SimulatedCRM.upsert`, which searches by `gde_key` before creating. A correction queues `crm_compensate` and `slack_retract`. `Engine._decide` applies seller suppressions and cooldowns and a per-rep daily cap. Play eligibility checks for an open deal, so a seller already in a deal gets an "add to the open deal" play, not a cold one. |

Berry's points that show up here:

- **Failures are constant.** The demo injects 13 failures (`faults.py:Faults`), including a Slack timeout after a successful post and a crash after a CRM write.
- **Tools sync behind your back.** Every side effect checks for its own earlier write before acting, because a retry may follow a write that did land.
- **Agent-written CRM data is marked.** Every CRM write carries a `gde_key`, so the system can find and revert only its own writes.
  It does not check for human edits before reverting.
- **The human-agent interface.** `Service.inspect` shows the inputs, rules, model calls, transitions and side effects for any decision.
  The seller can accept, snooze, dismiss or correct (`feedback/service.py:submit`).

## Comparison with LangChain's published GTM agents

- **"How we built LangChain's GTM Agent": trigger, check, gather context, Slack draft with reasoning and sources.** Same shape.
  A job-change webhook triggers `Engine.ingest`, the rules decide whether to act, and the card from `Engine._surface` carries the why-now, the evidence and a suggested opener.
  `Service.inspect` ties each piece of evidence to its source record.
  The seller's Accept is the approval that starts the CRM write-back.
- **Same post: learn rep style by diffing rep edits.** Not done.
  Feedback here changes decisions, not writing style.
  A correction stores an identity exclusion, suppresses a play, or opens a RevOps task.
  There is no per-rep memory of how they write.
- **"How we built LangChain's Paid Media Agent": a source of truth per metric, and keep uncertainty when data can't be joined.** Same idea.
  `precedence.json` names the winning source per field, `account_context` records conflicts instead of dropping them, and a CRM read failure means HOLD, not a guess.
  Ambiguous identity is a NEEDS_REVIEW state with a queue (`Service.reviews`).
- **Same post: model for judgment, code for computation and safeguards.** Same.
  Thresholds, freshness windows, cooldowns, play eligibility (`plays/registry.py:evaluate`) and caps are code.
- **Same post: isolation, and one runtime with capability profiles per entry point.** Similar.
  Each run has its own state row and each outbox row has its own status and attempt count, so one failing row does not block others.
  The same `gde` package runs behind FastAPI and in the browser through Pyodide.
  `Service._demo_only` turns off demo endpoints when `demo` is false.
- **"How We Built Our Design Agent": hard ordering in code, visible status, fast and slow loops.** Partly.
  Rule order is fixed in `Engine._decide`, each step writes a `Trace` entry, and the reliability panel (`Service.reliability`) shows dead letters.
  The fast loop is a seller correction that takes effect on the next decision.
  The slow loop is the eval suite and threshold sweep (`evals/threshold_sweep.py`), run by hand.
  The post's advice to delete rules as models improve does not apply yet; the model is kept out of the decisions those rules guard.

This repo does not use LangGraph, Deep Agents or LangSmith.
The package is the standard library behind FastAPI, so it also runs in Pyodide.
The workflow is short: decide, then one to three side effects.
The hard problems are side effects, identity and idempotency, for example making sure a Slack timeout after a post never creates a second card.
A framework does not solve those on its own.

## Not built here

- No per-rep learned memory or style learning from edits.
- No tracing or LangSmith.
  The trace and audit log live in SQLite (`audit.py:log`).
- No live integrations tested.
  Slack, CRM and enrichment are simulated.
  `AnthropicProvider` is tested only with a stubbed call.
- No waterfall enrichment across providers and no selective refresh schedule.
- Single process.
  The recovery sweeper runs once at startup and has no leases.
- No backoff with jitter, no re-driving dead letters from the UI, no webhook signature checks.
- No check for human edits before compensating a CRM write.
- No outbound email, so no deliverability or domain reputation work.

These comparisons are my reading of public posts; they are not claims about how those systems work internally beyond what the posts say.
