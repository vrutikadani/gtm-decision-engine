# ADR 0002: Identity resolution is deterministic, not an LLM

**Status:** accepted

## Context
"Is the Priya Raman in this vendor signal our Priya Raman?" decides whether a seller contacts someone on behalf of the company. A false match is costly and embarrassing. A missed match is a lost opportunity.

## Decision
`gde/champions/resolution.py`:
1. Candidates: same last name, or same profile URL (both indexed).
2. Hard constraints remove candidates. A human ruled them out before, their profile URL contradicts the signal, or they are already at the new company.
3. Independent features are combined as noisy-OR (`1 - Π(1 - w)`). Weights are in `config/thresholds.json`.
4. MATCH needs a score ≥ 0.80 **and** a margin ≥ 0.20 over the runner-up. A score ≥ 0.45 goes to REVIEW. Anything lower is NO_MATCH.

The thresholds come from a sweep over 24 labeled cases (`evals/threshold_sweep.py`). Between 0.75 and 0.85 there are no new critical errors. 0.80 sits in the middle of that plateau. At 0.95, scenario 5 would also go to review, but 19 of 24 cases would need a person.

## Consequences
- Every point of confidence is explainable in the trace and the review UI.
- REVIEW is a first-class outcome with a queue, not an error.
- Cost: more rules to maintain. Fuzzy cases (nicknames, transliterations) go to review instead of being matched cleverly.
- Known limitation: if our own CRM holds a wrong identifier, the resolver cannot know. The seller correction loop and a RevOps data-quality task cover it (scenario 5, eval case ID-23).
