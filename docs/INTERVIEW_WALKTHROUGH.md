# Interview walkthrough (7 to 10 minutes)

For me, not for the repo's readers. These are key points and transitions, not a script. Before the call: hosted demo loaded, `make demo` running, editor open on `engine.py` and `resolution.py`.

**Framing sentence:** "This is a public reference implementation with synthetic data. It shows how I design GTM systems: where rules decide, where a model helps, and where a person has to."

---

## 0:00–0:45 · Problem
**Screen:** overview page.

- Raw GTM alerts create seller homework. "Priya changed jobs" leaves the seller to answer:
  - Is it our Priya?
  - Was she a champion?
  - Is the account worth it?
  - Is there already a deal?
  - Who owns it?
  - What do I say?
- The system's job is to do that homework, or to say clearly that it could not.

**Transition:** "Here is how it is built, then I'll run it."

## 0:45–1:45 · Architecture
**Screen:** Architecture tab, diagram A, then B.

- Truth → Context → Decision → Action → Feedback.
- Headless: Slack is only delivery. The decision exists even when nothing is sent.
- Diagram B is the key slide:
  - code decides
  - the model labels intent, extracts quoted mentions and drafts one sentence
  - people own ambiguous identity and ownership changes

**Don't:** walk every box. Point at B and move on.

## 1:45–3:30 · Champion tracker
**Screen:** scenario 1.

- Run it, then read the flow strip left to right.
- Open "Why did the system decide this?":
  - identity 0.95, one candidate
  - champion evidence: three types, first-party
  - Tier 1, no open opportunity
  - `champion_reactivation` eligible
- Open the Sources tab: every line on the card has a record behind it.
- Press **Accept**. Inspector → Side effects: one Slack post, two CRM records with `gde_key`.

**Transition:** "That's the easy case. What I actually care about is what it does when it isn't sure."

## 3:30–4:30 · Uncertainty
**Screen:** scenario 2.

- Two Jordan Morales candidates, both at 0.47, margin 0.00. NEEDS_REVIEW.
- The point: no seller saw anything. Uncertainty is a state with a queue, not a confidence number hidden in a log.
- Optionally pick P-501 → it resumes, and the trace records the reviewer.

**Don't:** defend the exact weights here. Offer the threshold sweep if asked.

## 4:30–5:45 · GTM brief
**Screen:** scenario 3.

- Competitor Alpha: 2 of 6 conversations rises to 6 of 8.
- Click the claim: the eight conversations, quotes highlighted, window labels.
- "Numbers come from code. The model only finds mentions, and a mention must quote the source verbatim."
- Point at "Kept out of the brief": a pasted email tried to instruct the model. It was quarantined.

## 5:45–7:00 · Pipeline surface
**Screen:** scenario 4.

- One card that combines champion movement, Tier 1 fit, and an evaluation call 5 days ago.
- Read the card's fields: Account, Why now (with the quote and conversation id), Who, Evidence, Approved play, Next best action.
- The seller does not interpret raw signals. The play changed to the "active evaluation" version because the conversation context made it eligible.

## 7:00–8:00 · Feedback
**Screen:** scenario 5.

- The wrong Chris Walker: our CRM had someone else's profile URL, so 0.94 confidence.
- **Correct → Wrong person.** Show the effects:
  - exclusion under both subject keys
  - RevOps data-quality task
  - rerun → SUPPRESS
- Click "Second vendor, 20 days later, no profile URL": suppressed. Still one Slack message total.

## 8:00–9:00 · Hardest failure
**Screen:** scenario 6.

- "My first version passed the 'doesn't repeat the mistake' test and still left the CRM wrong."
- Before / after: association and task left live, versus reverted.
- Lesson: idempotency covers repeats, not reversal. Every write-back needs an inverse, and tests have to assert on downstream state.

## 9:00–10:00 · Tradeoffs
**Screen:** `docs/TRADEOFFS.md`, or nothing.

- **Build vs buy:** buy job-change data, enrichment and transcription. Build identity against our CRM, the champion definition, plays and corrections.
- **At production scale:**
  - Postgres and a queue
  - real CRM adapters with last-modified checks
  - owner-change re-routing
  - weights fitted from review outcomes
  - shadow mode for threshold changes
- Close: "The part I'd want to talk about is how you decide what the system is allowed to do on its own."

---

## If they interrupt
Let them. The best interviews leave the script by minute 3. The inspector and the trace answer most "what happens if" questions on screen. `docs/INTERVIEW_QA.md` has the rest.

## What not to over-explain
- Pyodide and how the demo is hosted (one sentence, only if asked)
- The UI
- Noisy-OR math, unless asked
