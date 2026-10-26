# Evaluation

`make eval` (or `python evals/run_eval.py`) runs three suites. CI fails on any blocking result.

## 1. Identity resolution: 24 labeled cases

Cases are in `evals/identity_cases.jsonl`. Each one is a signal plus the true answer: a person id, `null` (nobody we know), or `AMBIGUOUS` (even a human could not tell from the data). Results are graded by consequence, not by accuracy:

| Grade | Meaning | Cost |
|---|---|---|
| correct | Right person MATCHed; NO_MATCH when nobody; REVIEW when truly ambiguous | none |
| safe | REVIEW when the answer was knowable | a minute of someone's time |
| miss | NO_MATCH for a real person | a lost opportunity, nobody misled |
| critical | MATCH to the wrong person, or MATCH when it is nobody we know | a seller contacts a stranger as us |

Current result:

```
correct 16, safe 7, miss 0, critical 1
MATCH precision 9/10; sent to review 9/24
known limitation ID-23: the only identifier that could tell the two apart is wrong in our own CRM.
```

The one critical case is scenario 5 on purpose. The CRM contact carries another person's profile URL. No resolver could catch that from the data. It is tagged `known_limitation`, printed on every run, and covered by the seller correction loop instead. Any *other* critical result fails CI.

**The first run found two misses** (`docs/assets/eval_first_run.txt`):

- ID-11: a vendor typo in the last name, "Elena Brook"
- ID-12: a name change, "Priya Raman-Iyer"

Candidate generation was last-name only. Adding profile-URL candidates fixed both without new false matches.

### How the thresholds were chosen

`python evals/threshold_sweep.py` (output in `docs/assets/threshold_sweep.txt`):

```
match_min  correct safe miss critical(new)  sent_to_review
  0.70       19     2    0   3 (2)            3
  0.75       16     7    0   1 (0)            9
  0.80       16     7    0   1 (0)            9
  0.85       16     7    0   1 (0)            9
  0.90       15     8    0   1 (0)            10
  0.95        7    17    0   0 (0)            19
```

The rule was zero new critical cases first, then the fewest reviews. 0.75 to 0.85 is a plateau, and 0.80 sits in the middle so small weight changes do not fall off an edge. At 0.95 even scenario 5 goes to review, but so do 19 of 24 cases, and reviewers would stop reading.

## 2. Decisions: 11 end-to-end cases

`evals/decision_cases.json`. Each case runs a full signal through the engine against a fresh world and checks the outcome and the play. Cases include:

- the scenarios
- a stale signal
- an open opportunity (goes to the deal owner)
- a Tier 3 account
- a contact with only webinar attendance
- an unknown company
- do-not-contact
- an account mid-reassignment

Result: 11/11.

## 3. GTM brief: 5 checks

- Competitor counts match hand labels (`evals/brief_labels.json`): Alpha 2 → 6, Beta 2 → 1.
- Every citation quote appears verbatim in its source.
- The injected instruction in C-116 is quarantined.
- A fabricated quote (failure injection) is rejected and does not change any claim.

## What these numbers do and do not prove

- The sets are **small and synthetic**. They prove the rules do what the docs say, and they catch regressions. They do not prove real-world precision.
- In production, I would measure:
  - **review outcomes** as new labels: how often the reviewer picks the top candidate, picks another one, or picks none
  - **seller corrections by reason**: `wrong_person` is the false-positive rate that matters
  - **accept and execute rates per play**, and meetings created within 30 days of a card
  - **time from signal to card**, and the share of signals held, suppressed or sent to review, so silent over-suppression is visible
- Any threshold or play change would run in shadow mode against live signals before switching.

## Running against a real model

`GDE_LLM=anthropic ANTHROPIC_API_KEY=... python evals/run_eval.py` runs the brief and intent paths through Claude. The validators are the same, so a model that invents a quote fails the same check. Not run in CI (no key in CI, by design).
