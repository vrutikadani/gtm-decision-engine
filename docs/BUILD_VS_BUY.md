# Build vs buy

The rule I used: **buy data and plumbing that are commodities; build the judgment that encodes how this company sells.**

| Capability | Decision | Reasoning |
|---|---|---|
| Job-change detection | **Buy** (vendor adapters) | Tracking millions of profiles is a data business. Vendors do it at scale and own the compliance risk. |
| Firmographic enrichment | **Buy** | Commodity. Here it is non-critical: if it is down, the engine uses the cache. |
| Call recording and transcription | **Buy / integrate** | Not differentiated. We only read transcripts. |
| CRM | **Buy** (system of record) | The engine reads from it and writes back to it. It never replaces it. |
| Slack | **Buy** (delivery surface) | Sellers already live there. It is an adapter, not where the logic lives. |
| Identity resolution against *our* contacts | **Build** | Depends on our CRM's quirks and our tolerance for false positives. Vendors match to their own graph, not ours. |
| Champion definition | **Build** | "Two evidence types, one first-party" is our definition, from our usage data and deal history. No vendor has that data. |
| Account qualification and ownership rules | **Build** | ICP tiers, do-not-contact and realignment rules belong to RevOps. |
| Play registry | **Build** (as config) | This is the sales motion. It changes often and needs governance. |
| Feedback loop and corrections | **Build** | Corrections need to change our identity exclusions and suppressions, and undo our CRM writes. |
| Evaluation harness | **Build** | Labeled cases come from our own decisions and reviews. |
| LLM | **Buy** (API), bounded | Used for three narrow jobs, behind an interface with a deterministic fallback. |

## Why not an all-in-one tool?

Tools such as Clay, or the champion-tracking features of data vendors, cover the commodity half well: finding moves and enriching accounts. What this system needs on top of them:

- matching to *our* CRM with explicit uncertainty
- our definition of a champion
- our ownership and play rules
- corrections that change future behavior and clean up the CRM

A sensible production design uses a vendor or Clay as the **source** feeding `providers/job_change.py`, and keeps the decision layer in-house.

## When I would change my mind

- **Low volume.** If the team gets a handful of champion moves a month, a vendor's native alerts plus a weekly RevOps review is cheaper than owning a service.
- **A vendor exposes the hooks.** If a vendor supported custom match rules, review queues and write-back compensation, building would be harder to justify.
