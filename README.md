# GTM Decision Engine

Evidence-backed champion tracking, GTM intelligence, and pipeline decisions with explicit uncertainty, feedback, and evaluation.

**[Live demo](https://vrutikadani.github.io/gtm-decision-engine/)** · **[Architecture](docs/ARCHITECTURE.md)** · **[Quick start](#quick-start)** · [84-second walkthrough (mp4)](docs/assets/demo.mp4)

[![CI](https://github.com/vrutikadani/gtm-decision-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/vrutikadani/gtm-decision-engine/actions/workflows/ci.yml)

![A champion-reactivation decision with its rule-and-evidence trace](docs/assets/shot-hero.png)

> Synthetic reference implementation demonstrating GTM system architecture, decision boundaries, evaluation, and reliability. No employer data or proprietary production logic is included.

## What it does

Something happens: a former champion changes jobs, or competitors start coming up on calls. The system gathers context from the CRM, product usage and conversations, and evaluates it against explicit rules. Then it **makes or withholds** a decision. When it acts, a seller gets one card with the evidence and an approved play. Their feedback changes what it does next.

| | |
|---|---|
| **Decides** (code) | identity thresholds, champion evidence, ownership, suppression, cooldowns, play eligibility, state transitions, CRM write-back, idempotency |
| **Helps** (model, validated) | labels buying intent, extracts competitor mentions with verbatim quotes, drafts one sentence of copy |
| **Asks** (a person) | ambiguous identity, ownership in flux, corrections |

![Decision boundary](docs/assets/b-decision-boundary.png)

## Six scenarios

The live demo and `make demo` both have a scenario picker. Each scenario resets to the same seeded state, so it gives the same result every time.

| # | Scenario | What it shows |
|---|---|---|
| 1 | Confirmed champion movement | Signal → identity MATCH 0.95 → champion CONFIRMED → Tier 1, no open deal → Slack card → Accept → CRM write-back |
| 2 | Ambiguous identity | Two Jordan Morales score 0.47 each → NEEDS_REVIEW. No seller sees anything until a person picks. |
| 3 | GTM brief | Competitor Alpha 2/6 → 6/8 conversations. Click the claim to see the exact quotes. An injected instruction is quarantined. |
| 4 | Pipeline generation | Champion move + fit + an evaluation call 5 days ago → one card: Account, Why now, Who, Evidence, Play, Next best action |
| 5 | Seller correction | The wrong Chris Walker (our CRM had someone else's profile URL) → Correct → it does not come back, even from another vendor |
| 6 | Hardest failure | A correction that fixed future decisions but left the CRM wrong, before and after ([postmortem](docs/FAILURE_POSTMORTEM.md)) |

<table><tr>
<td><img src="docs/assets/shot-ambiguous-review.png" alt="Ambiguous identity in the review queue"><br><sub>2 · Ambiguous identity goes to review</sub></td>
<td><img src="docs/assets/shot-gtm-brief.png" alt="GTM brief with citations"><br><sub>3 · Every brief claim cites conversations</sub></td>
</tr><tr>
<td><img src="docs/assets/shot-seller-correction.png" alt="Seller correction"><br><sub>5 · Correction changes future behavior</sub></td>
<td><img src="docs/assets/shot-hardest-failure.png" alt="Hardest failure before and after"><br><sub>6 · Hardest failure, before / after</sub></td>
</tr></table>

Also in the demo:

- **System inspector:** inputs, context, evidence, rules, model calls, state transitions, side effects and feedback for any decision
- **Sources view**
- **Review queue**
- **Reliability panel**
- **Data explorer:** every record says why it exists
- **Failure injection** (demo only), with 12 injected failures:
  - duplicate webhook
  - second vendor reporting the same move
  - stale signal
  - CRM timeout
  - enrichment timeout
  - conflicting ownership
  - Slack 503
  - Slack timeout after post
  - crash after a CRM write
  - invalid transition
  - unsupported brief claim
  - ambiguous person

## Quick start

```bash
git clone https://github.com/vrutikadani/gtm-decision-engine
cd gtm-decision-engine
make demo
```

```
GTM Decision Engine running

Demo UI:
http://localhost:8000

API docs:
http://localhost:8000/docs

Demo scenarios loaded:
6

LLM provider: mock (deterministic)
No external API keys required.
```

Other targets: `make test` (40 tests), `make eval`, `python evals/threshold_sweep.py`. You can use Claude for the model calls with `GDE_LLM=anthropic ANTHROPIC_API_KEY=...`. The rules and validators stay the same.

## Evaluation

| Suite | Result |
|---|---|
| Identity: 24 labeled cases, graded by consequence | 16 correct, 7 safe (sent to review), 0 missed, 1 critical: a documented known limitation (scenario 5) |
| Decisions: 11 end-to-end cases | 11/11 |
| GTM brief: counts, citations, injection, fabricated quote | 5/5 |

CI fails on any new critical identity result. The first eval run found two real misses, which were then fixed. The thresholds come from a sweep, not from intuition. Details: [EVALUATION.md](docs/EVALUATION.md).

## How it is built

- **Headless:** one Python package (`gde/`, standard library only) behind a FastAPI app.
- **Hosted demo:** the *same package* runs in the browser through Pyodide on GitHub Pages. No server, no keys, nothing leaves the tab.
- **Storage:** SQLite, with explicit transactions.
- **Side effects:** decisions and their side effects are written together. A worker performs them, and every side effect looks for its own earlier write before acting (Slack: message metadata; CRM: a `gde_key` property).
- **Corrections:** a correction undoes the CRM writes it makes untrue.

| Doc | |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | What happens after the webhook arrives, with diagrams A to D |
| [docs/adr/](docs/adr/) | Nine decisions, each ending with the interview questions it triggers |
| [TRADEOFFS.md](docs/TRADEOFFS.md) · [BUILD_VS_BUY.md](docs/BUILD_VS_BUY.md) | What I chose, what it costs |
| [FAILURE_POSTMORTEM.md](docs/FAILURE_POSTMORTEM.md) | The hardest real failure found while building this |
| [SECURITY.md](docs/SECURITY.md) | PII, prompt injection, least privilege, demo-only controls |
| [CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md) | Product concept → file → function |
| [INTERVIEW_WALKTHROUGH.md](docs/INTERVIEW_WALKTHROUGH.md) · [3-minute version](docs/INTERVIEW_WALKTHROUGH_3_MIN.md) · [Q&A](docs/INTERVIEW_QA.md) · [Readiness check](docs/INTERVIEW_READINESS.md) · [Fallbacks](docs/DEMO_FALLBACKS.md) | Presenting it |

## Limitations

- The CRM and Slack are simulated adapters. Real API rate limits and search consistency are assumed, not tested.
- The evaluation sets are small and synthetic, and I wrote them.
- Not built:
  - re-routing cards when ownership changes after delivery
  - checking for human edits before compensating
  - webhook signature verification

Each one is discussed in the docs with what I would do.

## License

MIT
