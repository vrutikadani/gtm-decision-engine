# Failure postmortem: a correction that fixed the future but not the past

**Where it was found:** adversarial tests written while building this reference implementation (synthetic data). It did not happen in production, and nothing here describes an employer system.
**Severity:** high. The system of record ended up wrong while every dashboard looked healthy.
**Status:** fixed in the commit "Undo CRM writes when a seller corrects an accepted recommendation". Regression tests are in `tests/test_adversarial.py`. You can watch it in the demo as scenario 6.

## What happened

Scenario 5 sends Dana a card saying her former champion Chris Walker joined Redwood Plastic Surgery. Identity confidence is 0.94, because our CRM contact for Chris has a profile URL that matches the vendor's signal. The URL on the contact is wrong: it belongs to a different Chris Walker.

The failing sequence:

1. Dana presses **Accept**. The outbox worker writes to the CRM: it associates contact P-502 with Redwood and creates a task for Dana.
2. Dana calls, finds out it is the wrong person, and presses **Correct → wrong_person**.
3. The correction did what it was designed to do. It stored an identity exclusion, queued a RevOps data-quality task, and re-evaluated the signal, which returned `SUPPRESS`.
4. **Nothing undid step 1.** The CRM still said our champion works at Redwood, and Dana still had a task to email a stranger.

Captured output from the pre-fix code is in `docs/assets/hardest_failure_before.json`:

```
crm-associate_contact-1   associate_contact P-502 -> A-700   still live
crm-create_task-2         create_task rep-dana               still live
crm-data_quality_task-3   data_quality_task P-502            (correct)
```

## Why it was easy to miss

Every signal the system watched said things were fine:

- the run's state was `SUPPRESSED`
- the rerun's trace was correct
- the feedback loop test passed, because it checked that the mistake did not *repeat*

The damage was in another system, and nothing asserted on it. A wrong association in the CRM spreads to other places: routing, reporting, the next rep who opens the record, and other automations that read contacts by company.

## Why the architecture did not prevent it

The design handled **repeats** but not **reversal**.

- **Idempotency keys and search-before-create** guarantee each write happens at most once. They say nothing about a write that should no longer exist.
- **The state machine** allowed `ACCEPTED → CORRECTED`, which was right, but it treated the transition as a state change, not as an event with side effects.
- **The feedback service** was written forward-looking: "what should the system do next time?" It never asked "what did we already do because of this?"

The general lesson: every write-back needs a defined inverse, and every correction has to say which earlier writes it makes untrue.

## The fix

1. `COMPENSATE` in `gde/feedback/service.py` maps each correction reason to the write kinds it invalidates:
   - `wrong_person` and `wrong_account`: association, opportunity stakeholder, task
   - `wrong_play` and `already_engaged`: the task only. The association is still true, so it stays.
2. In the same transaction as the correction:
   - any pending write-back for that decision is cancelled
   - a `crm_compensate` outbox row is queued
3. `crm_compensate` in `gde/delivery/worker.py` looks at **what the CRM actually holds** for that decision, by `gde_key` prefix. It does not trust what we think we wrote, because a write-back can crash halfway with its outbox row still pending.
4. Compensating writes are idempotent too (`<key>:revert`), so replaying them is safe.

After the fix, the same sequence leaves zero wrong records (live in the demo, scenario 6).

## Regression tests

| Test | Guards against |
|---|---|
| `test_correction_after_accept_cleans_up_crm` | the original bug |
| `test_correction_after_a_crashed_writeback_still_cleans_up` | a partial write-back (crash after CRM write, row still pending) followed by a correction |
| `test_wrong_play_cancels_the_task_but_keeps_the_true_association` | over-correcting: deleting data that is still true |
| `test_correction_before_accept_reverts_nothing` | compensation that is not needed |
| `test_compensation_is_idempotent_on_replay` | double reverts when the worker replays |

## Other failures found in the same pass

These were smaller, and each is fixed in the same commit:

| Failure | Cause | Fix |
|---|---|---|
| A crash after Slack accepted a post caused a second post on retry | The worker only searched for an earlier post when `attempts > 0`. A crash leaves `attempts = 0`. | Always look up by message metadata before posting. |
| A wrong-person correction was forgotten when a second vendor reported the same move without a profile URL | Exclusions were stored under one subject key (the URL when present) | Store exclusions under every identifier the signal gives (`subject_keys`). |
| The audit row for a rejected state transition disappeared | It was written inside the transaction that then rolled back | `Store.after_rollback()` writes it after the rollback. |

The first evaluation run also found two identity misses: a vendor typo in a last name and a name change. Candidate generation by profile URL fixed them (commit "Identity: also take candidates by profile URL"; before and after output in `docs/assets/eval_first_run.txt` and `eval_latest.txt`).

## What I would still worry about

- **Humans edit CRM records too.** If a rep edits the task after we created it, compensation cancels it anyway. A production version should compare the record's last-modified-by before reverting, and route conflicts to a person.
- **The root cause is upstream.** A wrong profile URL in the CRM is a data-quality problem the resolver cannot see. That is why the correction also opens a RevOps task. I also kept the case in the eval set as a documented known limitation instead of deleting it.

## Interview questions this may trigger

- Why didn't idempotency cover this? *Idempotency stops a write from happening twice. It cannot tell you that a write should never have happened.*
- Why not just delete the records? *Some of them are still true (`wrong_play` keeps the association). Also, an audit trail of what was reverted and why matters more than a clean table.*
- What if the CRM write and the correction race? *The pending write-back is cancelled in the correction's transaction. If it already ran, compensation finds its records in the CRM by key.*
- How would you have caught this earlier? *Assert on downstream state, not only on the system's own state. The original test checked "does not repeat", never "is the CRM right".*
