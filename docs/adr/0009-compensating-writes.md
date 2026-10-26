# ADR 0009: Corrections undo the CRM writes they make untrue

**Status:** accepted (after the failure in `docs/FAILURE_POSTMORTEM.md`)

## Decision
Every correction reason declares which write kinds it invalidates (`COMPENSATE` in `gde/feedback/service.py`). A correction cancels pending write-backs for that decision and queues a `crm_compensate` row. The worker reverts what the CRM actually holds for that decision, idempotently.

## Consequences
- The CRM stays true after a wrong recommendation was accepted.
- `wrong_play` keeps a true association and only cancels the task.
- Cost: every new write kind needs a defined inverse before it ships.
- Not handled yet: a human edited the record after we created it. A production version should check last-modified-by and route conflicts to a person.

## Interview questions this decision may trigger
- What was the hardest bug?
- Why didn't your initial architecture prevent it?
- What if a human edited the CRM record in between?
