"""Cases written to break the system, not to demo it."""
from conftest import ev
from gde.delivery import worker


def test_crash_after_slack_post_does_not_double_post(svc):
    # worker dies after Slack accepted the message, before the outbox row is marked done
    import gde.delivery.worker as w
    real = w.state.transition
    calls = {"n": 0}

    def boom(s, clock, run_id, to, reason):
        if to == "DELIVERED" and calls["n"] == 0:
            calls["n"] += 1
            raise w.WorkerCrash("killed after post")
        return real(s, clock, run_id, to, reason)
    w.state.transition = boom
    try:
        try:
            svc.job_change(*ev(svc, "S1"))
        except w.WorkerCrash:
            pass
    finally:
        w.state.transition = real
    worker.process(svc)
    assert len(svc.slack.messages) == 1


def test_correction_after_accept_cleans_up_crm(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "accept")
    assert any(r["kind"] == "associate_contact" for r in svc.crm.records)
    svc.feedback(d["id"], "correct", reason="wrong_person")
    live = [r for r in svc.crm.records if r["kind"] in ("associate_contact", "create_task") and not r.get("reverted")]
    assert live == [], "CRM still says the wrong Chris Walker works at Redwood"


def test_wrong_person_is_remembered_when_another_vendor_reports_without_url(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "correct", reason="wrong_person")
    svc.advance(20)  # outside the cross-vendor dedupe window
    payload = {"event_id": "JS-7777", "person": {"full_name": "Chris Walker", "profile_url": None, "location": "San Diego"},
               "new_role": {"company": "Redwood Plastic Surgery", "domain": "redwood-ps.example", "title": "Office Manager",
                            "start_date": "2026-10-10"}, "previous_role": {"company": "Coastal Laser Center"},
               "detected_at": "2026-11-08T08:00:00Z"}
    d2 = svc.job_change("jobsignal", payload)
    assert d2["outcome"] == "SUPPRESS", d2["reason"]


# --- regressions for the hardest failure (docs/FAILURE_POSTMORTEM.md) -------------

def _live(svc, kinds=("associate_contact", "create_task", "add_opportunity_stakeholder")):
    return [r for r in svc.crm.records if r["kind"] in kinds and not r.get("reverted")]


def test_correction_after_a_crashed_writeback_still_cleans_up(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.faults.arm("crash_after_crm_write")
    svc.feedback(d["id"], "accept")          # CRM writes landed, outbox row still pending
    svc.feedback(d["id"], "correct", reason="wrong_person")
    worker.process(svc)
    assert _live(svc) == []
    assert svc.store.one("SELECT status FROM outbox WHERE kind='crm_writeback' AND decision_id=? "
                         "ORDER BY id LIMIT 1", (d["id"],))["status"] == "cancelled"


def test_wrong_play_cancels_the_task_but_keeps_the_true_association(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.feedback(d["id"], "accept")
    svc.feedback(d["id"], "correct", reason="wrong_play")
    assert [r["kind"] for r in _live(svc)] == ["associate_contact"]


def test_correction_before_accept_reverts_nothing(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "correct", reason="wrong_person")
    assert not [r for r in svc.crm.records if r["kind"] == "revert"]


def test_compensation_is_idempotent_on_replay(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "accept")
    svc.feedback(d["id"], "correct", reason="wrong_person")
    n = len(svc.crm.records)
    svc.store.x("UPDATE outbox SET status='pending' WHERE kind='crm_compensate'")  # replay the row
    worker.process(svc)
    assert len(svc.crm.records) == n


def test_scenarios_are_deterministic(svc):
    a = svc.run_scenario(1)
    trace_a = svc.trace(a["decision_id"])
    b = svc.run_scenario(1)
    assert a["decision_id"] == b["decision_id"] and svc.trace(b["decision_id"]) == trace_a
