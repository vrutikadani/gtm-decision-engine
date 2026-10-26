# Technical Q&A prep

Written as a skeptical Principal GTM Engineer and Staff Engineer would ask. Every strong answer points to something that exists in this repo. Where something is not built, the answer says so.

Format for each question: **Strong** answer · *Weak answer to avoid* · → follow-up they may ask.

---

## Architecture

**1. Why one system instead of separate tools for champions, briefs and routing?**
**Strong:** They share the same truth layer, the same play registry, the same feedback state and the same audit log. Scenario 4 only works because the champion engine and conversation context feed one decision. Separate tools would each need their own CRM context and would send overlapping alerts.
*Weak:* "It's cleaner."
→ What would you split out first at scale? *The brief pipeline. It is batch work on a schedule, while champion decisions are per-event.*

**2. Why headless?**
**Strong:** The decision exists before and without any message. That is what lets NEEDS_REVIEW and SUPPRESS be real outcomes with traces. The UI, Slack and the browser demo are all clients. `tests/test_api.py` checks that HTTP and browser expose the same routes. (ADR 0001)
*Weak:* "Best practice."
→ What does it cost? *A service to deploy, monitor and own on-call.*

**3. Why Slack only as delivery?**
**Strong:** It is where sellers already work, and the adapter is about 30 lines. Nothing about the decision depends on it. If Slack is down, decisions are still made and the outbox retries delivery.
*Weak:* "Sellers like Slack."
→ What if a seller ignores Slack? *Then the card should become a CRM task. That is another adapter; the decision does not change.*

**4. Why these module boundaries?**
**Strong:** Each module answers one question, and each can be wrong independently:
- providers: what did the vendor say?
- resolution: who is it?
- validation: were they a champion?
- truth: what do we believe about the account?
- qualification: is it worth acting on?
- plays: what are we allowed to do?
- delivery: did it get there?
- feedback: what changed?

The trace has one step per question, so a wrong outcome points at one module.
*Weak:* Listing the folders.
→ Where is the coupling you don't like? *`_surface` sits in the engine, and opener drafting lives there. I'd move it to delivery.*

**5. Why not Clay / Salesforce Flow / a vendor's champion tracker?**
**Strong:** I'd use them as sources. The parts I built are identity against *our* CRM with explicit uncertainty, *our* champion definition, governed plays, and corrections that change future behavior and clean up the CRM. Those are judgment, not data. (BUILD_VS_BUY.md)
*Weak:* "They're expensive" or "They can't do it."
→ When would you buy instead? *At low volume, or if a vendor exposed custom match rules, review queues and write-back compensation.*

## CRM

**6. What is the system of record?**
**Strong:** The CRM, for ownership, tier, lifecycle and open deals (`config/precedence.json`). If the CRM cannot be read, the decision is HOLD, never a guess from cache (`context/truth.py`, failure injection `crm_timeout`). Enrichment is used from cache when it is down, because it never decides anything.
*Weak:* "We sync everything to the warehouse."
→ What if CRM and enrichment disagree on tier? *The CRM wins, and the disagreement is recorded in the trace (Lakeside: CRM Tier 1, enrichment Tier 2).*

**7. How do you avoid duplicate writes?**
**Strong:** Every CRM record we create carries a `gde_key` like `DEC-0001:create_task`, and `upsert` searches for it before creating. The worker can crash after writing and replay the row safely (failure injection `crash_after_crm_write`).
*Weak:* "The CRM dedupes."
→ Real CRMs? *A custom property, indexed for search. HubSpot and Salesforce both support it; it costs one extra read.*

**8. How do you handle ownership changes?**
**Strong:** If the account has a reassignment pending, the decision goes to the RevOps review queue instead of either rep (`qualification.py`, injection `conflicting_ownership`). If the opportunity owner differs from the account owner, the open-deal play goes to the deal owner.
*Weak:* "We use round robin."
→ What if ownership changes after the card was sent? *Not handled here. I'd subscribe to owner-change events and re-route open cards. It is listed as a gap.*

**9. What happens when a seller is wrong about a correction?**
**Strong:** A `wrong_person` exclusion is a row in `identity_exclusions` with the decision id and time. RevOps can delete it. The audit log shows who said what. I would not let sellers undo exclusions themselves.
*Weak:* "Sellers are always right."

## Identity

**10. Why not use an LLM for identity resolution?**
**Strong:** A false match means a seller congratulates a stranger on behalf of the company. I need every point of confidence explainable and the same answer every time. The resolver is constraints, a noisy-OR over five features, and a margin rule, and the review UI shows exactly which features matched. (ADR 0002)
*Weak:* "LLMs hallucinate."
→ Where could a model help? *Normalizing messy titles or company names before matching, as a feature with a weight. Never as the decider.*

**11. How did you choose the thresholds?**
**Strong:** A sweep over 24 labeled cases (`evals/threshold_sweep.py`). The rule is zero new critical cases first, then the fewest reviews. 0.75 to 0.85 is a plateau, and 0.80 sits in its middle. At 0.70, two new false matches appear. At 0.95, 19 of 24 cases go to review. The margin rule (0.20) is what catches two candidates with the same name.
*Weak:* "0.8 felt right."
→ 24 cases isn't much. *Right. It is enough to show the method, not to set production numbers. In production, review outcomes become labels.*

**12. What is the cost of a false positive versus a false negative?**
**Strong:** A false positive is critical: a seller contacts a stranger as us, and the CRM can end up wrong. A false negative is a lost opportunity that nobody sees. A REVIEW costs a minute of RevOps time. The eval grades on exactly those consequences, not on accuracy.
*Weak:* "Both are bad."

**13. Scenario 5 shows a confident wrong match. Doesn't that undermine the design?**
**Strong:** It is the honest limit. Our own CRM held another person's profile URL, the strongest identifier. No resolver sees that from the data. I kept it in the eval set as a known limitation instead of deleting it. The answer is the loop around it: one-click correction, exclusion under every identifier, a RevOps data-quality task, and compensating CRM writes.
*Weak:* "That's an edge case."
→ Could you detect it? *Partly. A Clinical Director becoming an Office Manager is a weak hint. Title discontinuity could lower the score. I haven't added it, because one example isn't evidence.*

**14. Why last name OR profile URL for candidate generation?**
**Strong:** The first eval run missed a vendor typo ("Elena Brook") and a name change ("Raman-Iyer"). URL candidates fixed both without new false matches. Both columns are indexed, so this is not a table scan.

## Signals

**15. How do you handle stale signals?**
**Strong:** A signal older than 30 days is suppressed with the reason in the trace (injection `stale_signal`). A champion's evidence must be within three years. It is configured in one file.
*Weak:* "We process them in order."
→ Why suppress, not hold? *Old signals don't get fresher. Holding would just delay the same answer.*

**16. How do you deduplicate across providers?**
**Strong:** Two layers:
- same vendor and event id: a UNIQUE constraint, which also handles concurrent deliveries
- same normalized name and new company domain from any vendor within 14 days: `DUPLICATE` state

Injection `second_vendor_same_move` shows the second one.
→ What if they arrive 20 days apart? *That is a new run. If a seller had corrected the first one, the exclusion is stored under every identifier, so it is still suppressed (scenario 5 follow-up).*

## LLM

**17. Where exactly is the model used?**
**Strong:** Three calls in `llm/provider.py`:
- intent labels on prospect utterances
- competitor mentions with verbatim quotes
- one sentence of opener copy

The inspector's Model section shows each call, its input, its output and whether it passed validation.
*Weak:* "Throughout the pipeline."

**18. What happens when the model hallucinates?**
**Strong:** For mentions, the quote must appear verbatim in the cited utterance, or it is rejected and audited (injection `unsupported_brief_claim`). Counts come from code, so a hallucination can't inflate a number. For intent, the label must be in a closed set. For the opener, there are length, name, digit and competitor checks with a template fallback.
→ What about a plausible but wrong label? *That is the residual risk. Its blast radius is choosing between two approved plays, and corrections catch it.*

**19. How do you validate structured output?**
**Strong:** Closed sets, types and source cross-checks. If parsing fails, `FallbackProvider` uses the deterministic provider for that call and counts the error (`test_model_failure_falls_back_to_rules`).

**20. What about prompt injection in Gong transcripts?**
**Strong:**
- Transcripts are data.
- Utterances that look like instructions are quarantined before any model call, in both the brief and the decision path (C-116 in the demo; `test_injection_in_a_prospect_utterance_cannot_change_the_play`).
- The model has no tools and no write access.
- The worst case is a missed mention.
*Weak:* "We tell the model to ignore instructions."
→ Your regex will miss things. *Yes. The regex is the cheap first layer. The real defense is that the output cannot do anything except become a verbatim-checked mention.*

**21. Why a mock provider in the public demo?**
**Strong:** The demo must work without my key, at no cost, and deterministically. Same interface, same validators. Claude runs locally with `GDE_LLM=anthropic`.

## Evaluation

**22. What metrics matter?**
**Strong:** For identity: critical count (must be zero outside known limitations), then the review rate. For decisions: exact outcome and play. For briefs: count accuracy and citation integrity. In production: `wrong_person` correction rate, accept and execute rate per play, meetings within 30 days of a card, and the share held, suppressed or reviewed.
*Weak:* "Accuracy."

**23. How did you build labeled fixtures?**
**Strong:** By hand, each for a reason: typos, name changes, same name in the same city, same name at the same previous company, URL contradictions, missing fields. Each case has a note. The world's records carry `_why`. The first run found real misses, which I fixed.
→ Isn't that circular? *Partly. I wrote the cases and the rules. That is why the cases include ones that broke my first version, and why production labels would come from reviewers.*

**24. What would you measure in production?**
**Strong:** Review outcomes as labels (top candidate chosen, another chosen, none), corrections by reason, play outcomes, latency from signal to card, and silent over-suppression. Any threshold change runs in shadow mode first.

## Reliability

**25. What happens if Slack times out?**
**Strong:** A timeout is ambiguous. Every message carries our decision id in metadata, and before any post the worker searches for it. Found means DELIVERED, not found means post. Three attempts, then `DELIVERY_FAILED` on the reliability panel. Injections `slack_503` and `slack_timeout_after_post`.
*Weak:* "We retry."

**26. What if the CRM write succeeds but the workflow crashes before state is saved?**
**Strong:** The outbox row is still pending, so the worker replays it. `upsert` finds the records by `gde_key` and creates nothing new (injection `crash_after_crm_write`, `test_crash_after_crm_write_replays_without_duplicates`).

**27. How do you replay safely?**
**Strong:** Side effects are replayable because each one looks for itself first. Signals are not re-ingested blindly: the same event is a duplicate. Only HELD, CORRECTED and reviewed runs can be re-evaluated, which the state table enforces.
→ What about reprocessing history after a rule change? *Not built. I'd run the new rules in shadow mode over stored signals and diff the decisions before switching.*

**28. What does the state machine buy you?**
**Strong:** A stray click or replay can't move a run somewhere invalid. Execute-before-accept returns 409 and is audited (injection `invalid_transition`). An early bug: the audit row for the rejection rolled back with the transaction. Fixed with `after_rollback`.

## Security

**29. How do you protect PII?**
**Strong:** The model gets utterance text and four facts for the opener, never CRM records or emails. The demo is synthetic. In production: redact contact details in transcripts before extraction, log model calls without raw text, and use least-privilege CRM and Slack scopes (SECURITY.md).

**30. Webhook security?**
**Strong:** Not built in the demo, and documented. Production verifies vendor signatures and rejects replays outside a time window. Duplicate ids are already rejected.

## Scale

**31. What changes at 1,000 accounts?**
**Strong:** Nothing structural. SQLite handles it. The rep daily cap starts to matter.

**32. At 100,000 accounts?**
**Strong:** Postgres, a queue in front of ingest, workers per side-effect type, and CRM rate limits. Candidate lookup is already indexed by last name and URL. The brief becomes a scheduled batch over the warehouse.

**33. At 10M events?**
**Strong:** Partition decisions and audit by time, move traces to object storage with a summary row, and dedupe at the queue with the same keys. Most events would be suppressed early, so make the early steps cheap and measure suppression reasons.
*Weak:* "Kubernetes."

## Product

**34. Why these seller controls?**
**Strong:** Each one changes future behavior differently:
- accept: CRM write-back
- execute: task done
- snooze: resurfaces later
- dismiss: play suppressed for 30 days
- correct: requires a reason, and each reason does something specific

**35. Why snooze?**
**Strong:** "Not this week" is different from "no". Without snooze, sellers dismiss good cards and the system learns the wrong lesson.

**36. Why correction instead of just dismissal?**
**Strong:** Dismissal says "not useful". Correction says "wrong": wrong person, wrong play, already engaged, wrong account. Those need different fixes: an identity exclusion, a play suppression, a person suppression, a RevOps task. Corrections also undo the CRM writes they make untrue.

**37. How do you avoid spamming sellers?**
**Strong:** Most signals never reach them: duplicates, stale, not a champion, outside the ICP, reviews. There is a cap of 5 cards per rep per day, after which cards are held (`rep_daily_cap`, `test_rep_daily_cap_holds_the_sixth_card`).

## Adoption

**38. How would you know sellers trust it?**
**Strong:** Accept and execute rates per play, time from card to action, and corrections falling over time. The reliability panel has an adoption section. A rising `wrong_person` rate points at thresholds or CRM data quality. I'd also ask five sellers every two weeks, because rates don't tell you why.

## Build vs buy

**39. Why build champion logic?**
**Strong:** The champion definition uses our usage data and deal history (two types of evidence, one first-party). No vendor has that data.

**40. Why buy job-change data?**
**Strong:** Tracking millions of profiles is a data and compliance business. Our value is the judgment on top. Vendors are adapters, so switching one is one function.

## Failure

**41. What was the hardest bug?**
**Strong:** A correction that fixed the future but not the past. A seller accepted the Chris Walker card, then corrected it. The rerun was SUPPRESS, but the CRM still associated our champion with Redwood and the task was still open. Now corrections compensate. See the postmortem and scenario 6.

**42. Why didn't your initial architecture prevent it?**
**Strong:** It was built for repeats, not reversal. Idempotency stops a write from happening twice; it can't tell you a write shouldn't exist. And my test asserted on the system's own state, not on the CRM.

## Alternatives

**43. What would you do differently with six more months?**
**Strong:**
- real CRM adapters with last-modified checks before compensation
- owner-change re-routing
- shadow mode for rule changes
- weights fitted from review outcomes
- outcome attribution (card → meeting → pipeline) per play
- move opener drafting out of the engine

**44. What would you cut if you had to ship in two weeks?**
**Strong:** The brief and the browser demo. Keep identity with review, the play registry, the outbox, and corrections with compensation. Those are the parts that prevent harm.

**45. What's the weakest part of this repo?**
**Strong:** The evaluation set is small and written by me. Second, the CRM and Slack are simulated, so real API behavior (rate limits, partial failures, eventual consistency in search) is assumed, not tested.
