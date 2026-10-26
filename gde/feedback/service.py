"""Seller feedback. Every control changes state and future behavior, not just a counter.

  accept   -> CRM write-back (contact association, task) through the outbox
  execute  -> CRM task completed
  snooze   -> resurfaces after N days
  dismiss  -> this play is suppressed for this account for 30 days
  correct  -> a reason is required, and each reason teaches the system something specific:
      wrong_person    -> identity exclusion for this signal subject + RevOps data-quality task,
                         then the signal is re-evaluated without that candidate
      wrong_play      -> that play is suppressed for this account; re-evaluated
      already_engaged -> no prompts about this person at this account for 90 days
      wrong_account   -> RevOps task to fix the company/domain mapping
"""
from __future__ import annotations

import json
from datetime import timedelta

from .. import audit
from ..clock import fmt
from ..workflows import state

ACTIONS = {"accept": "ACCEPTED", "execute": "EXECUTED", "snooze": "SNOOZED", "dismiss": "DISMISSED",
           "correct": "CORRECTED"}
CORRECTIONS = {"wrong_person", "wrong_play", "already_engaged", "wrong_account"}
# What each correction makes untrue in the CRM, if the seller had already accepted.
COMPENSATE = {
    "wrong_person": ["associate_contact", "add_opportunity_stakeholder", "create_task"],
    "wrong_account": ["associate_contact", "add_opportunity_stakeholder", "create_task"],
    "wrong_play": ["create_task"],
    "already_engaged": ["create_task"],
}


class FeedbackError(ValueError):
    pass


def _suppress(s, clock, scope, key, days, reason):
    until = fmt(clock.now() + timedelta(days=days))
    s.x("INSERT OR REPLACE INTO suppressions VALUES(?,?,?,?,?)", (s.next_id("SUP"), scope, key, until, reason))
    return until


def submit(svc, decision_id: str, action: str, reason: str | None = None, days: int | None = None,
           note: str | None = None, actor: str = "seller") -> dict:
    s, clock = svc.store, svc.clock
    d = s.doc("decisions", decision_id)
    if d is None:
        raise FeedbackError("unknown decision")
    if action not in ACTIONS:
        raise FeedbackError(f"action must be one of {sorted(ACTIONS)}")
    if action == "correct" and reason not in CORRECTIONS:
        raise FeedbackError(f"correct needs a reason: one of {sorted(CORRECTIONS)}")
    latest = s.one("SELECT id FROM decisions WHERE run_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (d["run_id"],))
    if latest["id"] != decision_id:
        raise FeedbackError("this recommendation was superseded by a newer decision")
    run_id, effects, rerun = d["run_id"], [], False
    with s.tx():
        state.transition(s, clock, run_id, ACTIONS[action], f"seller {action}" + (f": {reason}" if reason else ""))
        fid = s.next_id("FB")
        s.x("INSERT INTO feedback VALUES(?,?,?,?)", (fid, decision_id, clock.iso(), json.dumps(
            {"id": fid, "decision_id": decision_id, "action": action, "reason": reason, "days": days, "note": note,
             "actor": actor, "at": clock.iso()})))
        acct, person, play = d["account_id"], d["person_id"], d["play"]
        if action == "accept":
            writes = []
            p = next(x for x in svc.plays if x["id"] == play)
            for w in p["crm_writes"]:
                fields = {"associate_contact": {"contact": person, "company": acct},
                          "create_task": {"owner": d["surface"]["owner"]["id"], "subject": d["surface"]["next_best_action"]},
                          "add_opportunity_stakeholder": {"contact": person, "role": "champion"}}[w]
                writes.append({"kind": w, "key": f"{decision_id}:{w}", "fields": fields})
            s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), decision_id, "crm_writeback", "pending", 0,
                None, json.dumps({"writes": writes})))
            effects.append(f"queued {len(writes)} CRM writes")
        elif action == "execute":
            s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), decision_id, "crm_writeback", "pending", 0,
                None, json.dumps({"writes": [{"kind": "complete_task", "key": f"{decision_id}:complete_task",
                                              "fields": {"task_key": f"{decision_id}:create_task", "status": "done"}}]})))
            effects.append("queued CRM task completion")
        elif action == "snooze":
            n = days or svc.cfg["snooze_default_days"]
            until = fmt(clock.now() + timedelta(days=n))
            s.x("UPDATE runs SET doc=? WHERE id=?", (json.dumps({"snoozed_until": until, "decision_id": decision_id}), run_id))
            effects.append(f"resurfaces {until}")
        elif action == "dismiss":
            until = _suppress(s, clock, "play_account", f"{play}|{acct}", svc.cfg["dismiss_suppress_days"],
                              f"dismissed by seller{': ' + note if note else ''}")
            effects.append(f"{play} suppressed for {acct} until {until}")
        elif action == "correct":
            # Undo first. A correction that only fixes future decisions leaves the CRM saying
            # whatever the wrong recommendation wrote (see FAILURE_POSTMORTEM.md).
            cancelled = s.x("UPDATE outbox SET status='cancelled', last_error='recommendation corrected' "
                            "WHERE decision_id=? AND kind='crm_writeback' AND status='pending'", (decision_id,)).rowcount
            if cancelled:
                effects.append(f"cancelled {cancelled} pending CRM write-back")
            s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), decision_id, "crm_compensate", "pending",
                0, None, json.dumps({"kinds": COMPENSATE[reason], "reason": f"seller correction: {reason}"})))
            effects.append("queued CRM compensation (undoes any write-back already made)")
            if reason == "wrong_person":
                for key in d["subject_keys"]:
                    s.x("INSERT OR REPLACE INTO identity_exclusions VALUES(?,?,?,?)",
                        (key, person, clock.iso(), f"seller said wrong person ({decision_id})"))
                s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), decision_id, "crm_writeback", "pending",
                    0, None, json.dumps({"writes": [{"kind": "data_quality_task", "key": f"{decision_id}:dq",
                    "fields": {"queue": "revops", "contact": person,
                               "subject": f"Seller says job-change match for {person} was the wrong person. "
                                          "Check the contact's profile URL and identifiers."}}]})))
                effects += [f"excluded {person} for {', '.join(d['subject_keys'])}", "RevOps data-quality task queued"]
                rerun = True
            elif reason == "wrong_play":
                until = _suppress(s, clock, "play_account", f"{play}|{acct}", svc.cfg["dismiss_suppress_days"],
                                  "seller said wrong play")
                effects.append(f"{play} suppressed for {acct} until {until}")
                rerun = True
            elif reason == "already_engaged":
                until = _suppress(s, clock, "person_account", f"{person}|{acct}", svc.cfg["already_engaged_suppress_days"],
                                  "seller is already engaged with this person")
                effects.append(f"no prompts for {person} at {acct} until {until}")
            elif reason == "wrong_account":
                s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), decision_id, "crm_writeback", "pending",
                    0, None, json.dumps({"writes": [{"kind": "data_quality_task", "key": f"{decision_id}:dq",
                    "fields": {"queue": "revops", "subject": f"Company mapping for {d['signal']['new_domain']} looks wrong"}}]})))
                effects.append("RevOps task to fix company mapping")
        audit.log(s, clock, "feedback", run_id, decision=decision_id, action=action, reason=reason, effects=effects)
    from ..delivery import worker
    worker.process(svc)
    out = {"feedback_id": fid, "state": s.one("SELECT state FROM runs WHERE id=?", (run_id,))["state"], "effects": effects}
    if rerun:
        out["rerun"] = svc.engine.evaluate(run_id)
        worker.process(svc)
    return out


def wake_snoozed(svc) -> list[str]:
    s, clock, woke = svc.store, svc.clock, []
    for r in s.all("SELECT * FROM runs WHERE state='SNOOZED'"):
        doc = json.loads(r["doc"] or "{}")
        if doc.get("snoozed_until") and doc["snoozed_until"] <= clock.iso():
            with s.tx():
                state.transition(s, clock, r["id"], "DELIVER_PENDING", "snooze expired")
                d = s.doc("decisions", doc["decision_id"])
                s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), d["id"], "slack", "pending", 0, None,
                    json.dumps({"channel": d["surface"]["owner"]["slack"], "key": d["id"] + ":resurface"})))
            woke.append(r["id"])
    return woke
