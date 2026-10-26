# ADR 0003: Buy job-change data; build the judgment on top

**Status:** accepted

## Context
Job-change detection means tracking millions of profiles. It is a commodity data business with compliance exposure (scraping terms of service).

## Decision
Vendors are adapters (`gde/providers/job_change.py`). Two vendor shapes (`jobsignal`, `careerwire`) normalize into one `JobChange` record. Everything that is ours stays in our code: who counts as a champion, what qualifies an account, which play is allowed, how feedback changes behavior.

## Consequences
- Adding or switching a vendor means one adapter function.
- The same move reported by two vendors collapses into one signal (`move_key`, 14-day window).
- Cost: vendor dependence, vendor-specific gaps (one sends no profile URL), and paying for coverage we do not use.

