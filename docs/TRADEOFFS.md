# Tradeoffs

The major decisions, the alternative I did not take, and what each choice costs. The ADRs in `docs/adr/` have the detail.

| Decision | Choice | Alternative | Why | Cost |
|---|---|---|---|---|
| Decision layer | Headless Python service | Slack workflow / Salesforce Flow / Clay | Rules are testable and versioned, and they work for any delivery surface | A service to deploy and operate |
| Identity | Rules + noisy-OR score + margin + human review | LLM match | Auditable; uncertainty is explicit | More rules; fuzzy cases go to review |
| Thresholds | 0.80 match / 0.20 margin / 0.45 review, from a sweep | Tuned by feel | Middle of the zero-new-critical plateau | 9 of 24 eval cases need a person |
| Job-change data | Vendor adapters | Build a scraper | Commodity data with compliance risk | Vendor dependence and gaps |
| Conversations | Read transcripts from the existing tool | Own transcription | Not differentiated | External dependency |
| Plays | Config registry, priority order | Model-generated actions | Governance; per-play reporting | Less flexibility |
| Model role | Intent labels, mention extraction, one sentence of copy | Model writes the brief / the card | Every number and claim is code-computed and cited | Underuses the model |
| Side effects | Outbox + search-before-create | Call APIs inline | Safe replays after crashes and timeouts | Extra read per effect; a worker |
| Corrections | Compensating CRM writes | Only stop future decisions | The CRM stays true (see postmortem) | Every write kind needs an inverse |
| Ownership in flux | RevOps review | Deliver to the current owner | Avoids telling the wrong rep | Slower during realignments |
| CRM unavailable | HOLD and retry | Decide on cached CRM data | Never deliver without knowing about open deals | Delays during outages |
| Enrichment unavailable | Use the cache and say so | HOLD | Firmographics never decide anything here | Slightly stale context |
| Seller capacity | 5 cards per rep per day, then HOLD | No cap | Protects the channel's signal-to-noise | Some cards wait a day |
| Persistence | SQLite, state + transitions + audit tables | Event store | Simple; history is still auditable | No projection rebuilds; single writer |
| Public demo | Real engine in the browser (Pyodide) | Hosted API | No server, no keys, nothing leaves the browser | 10 MB first load; CDN dependency |
| Test data | 9 accounts, 7 people, 14 conversations, each with a purpose | Thousands of generated rows | Every scenario is explainable live | Small eval set; synthetic labels |

## What I would change at production scale

- **Postgres** instead of SQLite, with row locks on runs and a queue in front of ingest.
- **Real HubSpot or Salesforce adapters**, with conflict checks: last-modified-by before compensating, and owner-change webhooks to re-route cards already sent.
- **Weights fitted from review outcomes** once there are a few thousand labeled reviews, keeping the margin rule.
- **Shadow mode** for any threshold or play change: run both versions on live signals and compare before switching.
