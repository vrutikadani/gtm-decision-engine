# ADR 0004: Plays come from an approved registry, never from the model

**Status:** accepted

## Context
"What should the seller do?" is the part leaders most want to control: messaging, offers, who is allowed to contact whom.

## Decision
`config/plays.json` lists the approved plays in priority order, each with explicit requirements. `gde/plays/registry.py` evaluates every play and records why it passed or failed. The first eligible play wins. The model writes one sentence of opener copy from four given facts. Code checks that sentence (length, first name present, no numbers, no competitor names) before it is shown.

## Consequences
- RevOps can review plays as config, with an eval run, without reading code.
- Every card names its play id, which makes outcome reporting per play possible.
- Cost: less flexibility. A situation no play covers gets SUPPRESS, not a creative suggestion. I think that is the right default.

