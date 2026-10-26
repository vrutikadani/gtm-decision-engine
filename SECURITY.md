# Security and data handling

## This repository
- **Synthetic data only.** Every company, person, conversation and competitor in `gde/fixtures/world.json` is invented. No employer data, credentials or proprietary production logic is included.
- **No secrets.** The public demo needs no keys. The optional model provider reads `ANTHROPIC_API_KEY` from the environment locally, and it is never committed or sent to the browser.
- **Fault injection is demo-only.** `Faults(enabled=False)` raises on any attempt to arm a fault, and every `/demo/*` endpoint (reset, scenarios, failures, clock) returns 403 when the service runs with `GDE_DEMO=0` (`tests/test_reliability.py::test_fault_injection_disabled_outside_demo`).
- **Supply chain.** The core engine uses only the standard library. FastAPI and uvicorn are pinned for the local server. CI runs CodeQL, and Dependabot checks pip and GitHub Actions weekly.

## Design choices that matter for a real deployment

**PII**
- The model receives utterance text only: no emails, no CRM fields, no names beyond what the speaker said.
- The opener draft gets four facts: first name, new account, previous company, and the seller context.
- Production should redact emails and phone numbers in transcripts before extraction, and log model calls without raw text.

**Prompt injection**
- Transcript text is data. Utterances that look like instructions are quarantined before any model call, in both the brief and the decision path.
- The model has no tools and no write access. Its output is schema-checked, and quotes must match the source verbatim.
- The worst outcome of a successful injection is a missed mention, not a changed decision. The failure injection `unsupported_brief_claim` and `tests/test_readiness.py::test_injection_in_a_prospect_utterance_cannot_change_the_play` demonstrate this.

**Least privilege**
- The CRM adapter needs read access to accounts, contacts and opportunities.
- It needs write access only to associations, tasks and one custom property (`gde_key`).
- Slack needs `chat:write`, plus the history scope for the conversations it posts to (`im:history` for DMs), which the idempotency lookup uses.

**Audit**
- Every decision, side effect, rejection, quarantine and state transition is written to the append-only `audit` table, including rejected transitions.

**Webhooks**
- Production must verify vendor signatures and reject replays outside a time window.
- The demo does not do this, and says so here.

## Reporting a vulnerability
Please open a GitHub security advisory on this repository. Do not open a public issue.
