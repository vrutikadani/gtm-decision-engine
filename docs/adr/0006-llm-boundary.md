# ADR 0006: The model gets three bounded jobs, all validated by code

**Status:** accepted

## Decision
`gde/llm/provider.py` is the only place a model is called:

| Job | Used by | Validation |
|---|---|---|
| `classify_intent` | Decision engine: buying intent in prospect utterances | Label must be in a closed set or it is dropped; confidence is clamped to [0, 1]; code applies the confidence and age cutoffs (`engine.validate_intent`) |
| `extract_mentions` | GTM brief | The quote must appear verbatim in the cited utterance; the competitor must be known |
| `draft_opener` | Seller card | Length, first name present, no digits, no competitor names; template fallback. Called outside any DB transaction (`Engine._draft_opener`) |

The model never sees the CRM, never picks a person, play or owner, and never writes. Counts and claims in the brief are computed by code. Text that looks like instructions to an AI is quarantined before any model call, in both the brief and the decision path.

The public demo uses a deterministic `MockProvider`. A real model is optional (`GDE_LLM=anthropic`). It is wrapped in `FallbackProvider`, so a timeout or malformed output falls back to the rules for that call. `AnthropicProvider` implements all three jobs. It is tested only with a stubbed API call (`tests/test_outbox_and_ordering.py::test_anthropic_draft_opener_is_validated_by_the_engine`), not against the live model.

Correction to an earlier version: `classify_intent` output was marked `validated: false` but still used, so a label like `BUY_NOW!!` with confidence 5.0 reached a seller card. Validation is now enforced, not only recorded. And `AnthropicProvider` used to inherit the mock template for `draft_opener`, so the real model never wrote copy.

## Consequences
- A hallucinated quote is rejected, not reported (failure injection `unsupported_brief_claim`).
- Prompt injection can at most cause one mention to be missed. It cannot change a number, a tier or a play.
- Cost: the model's best abilities (synthesis, nuance) are deliberately underused.
