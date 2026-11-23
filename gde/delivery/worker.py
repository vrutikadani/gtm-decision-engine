"""Outbox worker. Decisions and their side effects are written in one transaction as
outbox rows; this worker performs them. If it crashes midway, the row is still
pending and the next pass redoes it, which is only safe because every side effect
looks for its own earlier write first (Slack: message metadata; CRM: gde_key).

Every row kind (Slack post, CRM write-back, CRM compensation) gets the same failure
handling: an exception from the adapter is caught per row, counted as one attempt,
and the row stays pending for the next pass. After `delivery_max_attempts` the row
is dead-lettered (status 'dead') and the run is flagged so the reliability panel
shows it. One failing row never stops the other rows from being processed."""
from __future__ import annotations

import json

from .. import audit
from ..workflows import state

# outbox kind -> what a dead row means for the run
DEAD_FLAG = {"crm_writeback": "WRITEBACK_FAILED", "crm_compensate": "COMPENSATION_FAILED",
             "slack_retract": "RETRACTION_FAILED"}


class WorkerCrash(Exception):
    """Simulated process death. Not caught per row: the whole pass stops, as it would."""


def _bump(store, row, status, err):
    store.x("UPDATE outbox SET status=?, attempts=attempts+1, last_error=? WHERE id=?", (status, err, row["id"]))


def deliver_slack(svc, row) -> None:
    s, clock, slack = svc.store, svc.clock, svc.slack
    doc = json.loads(row["doc"])
    run_id = s.one("SELECT run_id FROM decisions WHERE id=?", (row["decision_id"],))["run_id"]
    # Always look first, not only on retries: a worker killed after Slack accepted the post
    # but before this row was saved has attempts == 0 and still must not post again.
    found = slack.find_by_metadata(doc["channel"], doc["key"])
    if found:
        with s.tx():
            s.x("UPDATE outbox SET status='done', doc=? WHERE id=?",
                (json.dumps({**doc, "ts": found["ts"], "recovered": True}), row["id"]))
            state.transition(s, clock, run_id, "DELIVERED", "found earlier post by metadata (timeout or crash)")
            audit.log(s, clock, "slack_recovered_existing_post", run_id, ts=found["ts"], attempt=row["attempts"] + 1)
        return
    decision = s.doc("decisions", row["decision_id"])
    msg = slack.post(doc["channel"], decision["surface"], doc["key"])  # errors are handled by process()
    with s.tx():
        s.x("UPDATE outbox SET status='done', attempts=attempts+1, doc=? WHERE id=?",
            (json.dumps({**doc, "ts": msg["ts"]}), row["id"]))
        state.transition(s, clock, run_id, "DELIVERED", f"posted to {doc['channel']}")
        audit.log(s, clock, "slack_posted", run_id, channel=doc["channel"], ts=msg["ts"], attempt=row["attempts"] + 1)


def crm_writeback(svc, row) -> None:
    s, clock, crm = svc.store, svc.clock, svc.crm
    doc = json.loads(row["doc"])
    run_id = s.one("SELECT run_id FROM decisions WHERE id=?", (row["decision_id"],))["run_id"]
    results = []
    for w in doc["writes"]:
        r = crm.upsert(w["kind"], w["key"], w["fields"])
        results.append({"key": w["key"], "crm_id": r["id"], "created": r["created"]})
        audit.log(s, clock, "crm_write" if r["created"] else "crm_write_skipped_existing", run_id,
                  key=w["key"], crm_id=r["id"])
    if svc.faults.fire("crash_after_crm_write"):
        with s.tx():
            _bump(s, row, "pending", "worker crashed after CRM write, before saving state")
            audit.log(s, clock, "worker_crashed", run_id, outbox=row["id"])
        raise WorkerCrash("worker crashed after CRM write")
    with s.tx():
        s.x("UPDATE outbox SET status='done', attempts=attempts+1, doc=? WHERE id=?",
            (json.dumps({**doc, "results": results}), row["id"]))


def crm_compensate(svc, row) -> None:
    """Undo CRM writes made for a recommendation the seller has since corrected. Looks at
    what the CRM actually holds (not what we think we wrote), so a write-back that
    crashed halfway is cleaned up too."""
    s, clock, crm = svc.store, svc.clock, svc.crm
    doc = json.loads(row["doc"])
    run_id = s.one("SELECT run_id FROM decisions WHERE id=?", (row["decision_id"],))["run_id"]
    done = []
    for rec in crm.find_prefix(row["decision_id"] + ":"):
        if rec["kind"] in doc["kinds"] and not rec.get("reverted"):
            r = crm.revert(rec["gde_key"], f"{rec['gde_key']}:revert", doc["reason"])
            done.append(r["id"])
            audit.log(s, clock, "crm_compensating_write", run_id, target=rec["gde_key"], action=r["action"])
    with s.tx():
        s.x("UPDATE outbox SET status='done', attempts=attempts+1, doc=? WHERE id=?",
            (json.dumps({**doc, "reverted": done}), row["id"]))


def slack_retract(svc, row) -> None:
    """Edit every card already posted for a corrected recommendation (the original and
    any resurfaced copy) so the seller no longer sees it as live advice."""
    s, clock, slack = svc.store, svc.clock, svc.slack
    doc = json.loads(row["doc"])
    run_id = s.one("SELECT run_id FROM decisions WHERE id=?", (row["decision_id"],))["run_id"]
    edited = []
    for m in slack.find_prefix(doc["channel"], row["decision_id"]):
        if (m["blocks"] or {}).get("retracted"):
            continue
        slack.update(m["channel"], m["ts"], {"retracted": True, "decision_id": row["decision_id"],
                                             "text": f"Withdrawn: {doc['reason']}. No action needed on this card.",
                                             "original": m["blocks"]})
        edited.append(m["ts"])
        audit.log(s, clock, "slack_card_retracted", run_id, ts=m["ts"], reason=doc["reason"])
    with s.tx():
        s.x("UPDATE outbox SET status='done', attempts=attempts+1, doc=? WHERE id=?",
            (json.dumps({**doc, "edited": edited}), row["id"]))


HANDLERS = {"slack": deliver_slack, "crm_writeback": crm_writeback, "crm_compensate": crm_compensate,
            "slack_retract": slack_retract}


def _fail(svc, row, err: str) -> None:
    """One failed attempt. Pending until the cap, then dead-lettered and the run flagged."""
    s, clock = svc.store, svc.clock
    run_id = s.one("SELECT run_id FROM decisions WHERE id=?", (row["decision_id"],))["run_id"]
    attempt = row["attempts"] + 1
    final = attempt >= svc.cfg["delivery_max_attempts"]
    with s.tx():
        s.x("UPDATE outbox SET status=?, attempts=?, last_error=? WHERE id=?",
            ("dead" if final else "pending", attempt, err, row["id"]))
        kind = "slack" if row["kind"].startswith("slack") else "crm"
        audit.log(s, clock, f"{kind}_attempt_failed", run_id, outbox=row["id"], row_kind=row["kind"],
                  attempt=attempt, error=err, final=final)
        if not final:
            return
        audit.log(s, clock, "outbox_dead_lettered", run_id, outbox=row["id"], row_kind=row["kind"], attempts=attempt)
        if row["kind"] == "slack":
            try:
                state.transition(s, clock, run_id, "DELIVERY_FAILED", f"Slack failed {attempt} times: {err}")
            except state.InvalidTransition:
                pass  # the run moved on (e.g. corrected); the dead row and audit entry still record it
        else:
            state.flag(s, clock, run_id, DEAD_FLAG[row["kind"]], f"{row['kind']} {row['id']} failed {attempt} times: {err}")


def process(svc, max_passes: int = 5) -> dict:
    """Drain pending outbox rows. Retries happen across passes (backoff is simulated)."""
    crashed = 0
    for _ in range(max_passes):
        rows = svc.store.all("SELECT * FROM outbox WHERE status='pending' ORDER BY id")
        if not rows:
            break
        for row in rows:
            try:
                HANDLERS[row["kind"]](svc, row)
            except WorkerCrash:
                crashed += 1
                return {"crashed": crashed, "pending": len(rows)}
            except Exception as e:  # noqa: BLE001 - any adapter error is one failed attempt for this row only
                _fail(svc, row, f"{type(e).__name__}: {e}")
    pending = svc.store.one("SELECT COUNT(*) n FROM outbox WHERE status='pending'")["n"]
    dead = svc.store.one("SELECT COUNT(*) n FROM outbox WHERE status='dead'")["n"]
    return {"crashed": crashed, "pending": pending, "dead": dead}
