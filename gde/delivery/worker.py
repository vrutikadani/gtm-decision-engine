"""Outbox worker. Decisions and their side effects are written in one transaction as
outbox rows; this worker performs them. If it crashes midway, the row is still
pending and the next pass redoes it, which is only safe because every side effect
looks for its own earlier write first (Slack: message metadata; CRM: gde_key)."""
from __future__ import annotations

import json

from .. import audit
from ..workflows import state
from .slack import SlackError, SlackTimeout


class WorkerCrash(Exception):
    pass


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
    try:
        msg = slack.post(doc["channel"], decision["surface"], doc["key"])
    except (SlackTimeout, SlackError) as e:
        with s.tx():
            final = row["attempts"] + 1 >= svc.cfg["delivery_max_attempts"]
            _bump(s, row, "failed" if final else "pending", str(e))
            audit.log(s, clock, "slack_attempt_failed", run_id, attempt=row["attempts"] + 1, error=str(e), final=final)
            if final:
                state.transition(s, clock, run_id, "DELIVERY_FAILED", f"Slack failed {row['attempts'] + 1} times: {e}")
        return
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


HANDLERS = {"slack": deliver_slack, "crm_writeback": crm_writeback, "crm_compensate": crm_compensate}


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
    pending = svc.store.one("SELECT COUNT(*) n FROM outbox WHERE status='pending'")["n"]
    return {"crashed": crashed, "pending": pending}
