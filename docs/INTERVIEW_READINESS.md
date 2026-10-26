# Interview readiness check

Before calling this done, I ran a mock 30-minute technical interview against the repo from four seats. The rule was that any question without a credible answer from the *implementation* gets fixed in the system, not with a better answer.

## Seat 1: Principal GTM Systems leader

| Question | Credible before? | Action |
|---|---|---|
| Where does the model run, exactly? | Yes: three calls, shown in the inspector | none |
| Your docstring says the real model "falls back to the mock on any error". Does it? | **No.** It was not implemented. | Added `FallbackProvider` and `test_model_failure_falls_back_to_rules` |
| You quarantine injected text in briefs. What about the decision path? | **No.** Intent labels read prospect utterances unfiltered, so an injection could pick a different play. | Same quarantine in the decision path, plus `test_injection_in_a_prospect_utterance_cannot_change_the_play` |
| How did you pick 0.80? | Partly: "the eval passes" | Added `evals/threshold_sweep.py`; the plateau argument is in EVALUATION.md |

## Seat 2: Staff Software Engineer

| Question | Credible before? | Action |
|---|---|---|
| Candidate generation scans every contact? | **Yes, it did** (full table read) | Indexed `last_name` and `profile_url` columns; the query uses them |
| Two copies of the same webhook at once? | **No.** The UNIQUE constraint would raise a 500. | `IntegrityError` is caught and retried as a duplicate |
| Is the hosted demo the real code? | Yes: same package; route parity and manifest tests | none |
| Can `/demo/reset` run in production? | **No guard on reset or the clock** | Every demo endpoint is gated; the test was extended |
| What happens after Slack times out? CRM crash? | Yes: injections plus tests | none |

## Seat 3: Revenue Operations leader

| Question | Credible before? | Action |
|---|---|---|
| Who owns ambiguous cases? | Yes: review queue, reviewer recorded in the trace | none |
| What if territories are being realigned? | Yes: RevOps queue | none |
| The diagram says "permissions" are deterministic. Where? | **No permission model exists.** The only rule is delivery to the account or deal owner. | Renamed to "ownership and routing" in diagram B instead of claiming more |
| How do I change a play? | Yes: `config/plays.json` plus a decision case | none |

## Seat 4: Seller

| Question | Credible before? | Action |
|---|---|---|
| Will this flood my DMs? | **No cap existed** | `rep_daily_cap` (5) holds extra cards, plus a test |
| If I correct it, does it come back? | Yes: scenario 5 follow-ups | none |
| How will you know if I trust it? | **No metrics** | Adoption section on the reliability panel (accepts, executes, corrections by reason) |

## Still open (said plainly in the docs)

- No re-routing when ownership changes after a card was sent.
- Compensation does not check whether a human edited the CRM record in between.
- Webhook signature verification is not implemented.
- The eval set is small, synthetic and written by me.
- The CRM and Slack are simulated. Real rate limits and search consistency are assumptions.

Each of these appears in `INTERVIEW_QA.md` as "not built", with what I would do.
