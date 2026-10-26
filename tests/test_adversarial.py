"""Cases written to break the system, not to demo it."""
import pytest

from conftest import ev
from gde.delivery import worker


@pytest.mark.xfail(strict=True, reason="found 2026-10-26: retry skips the metadata lookup when attempts == 0")
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


@pytest.mark.xfail(strict=True, reason="found 2026-10-26: correction fixes future decisions but not CRM writes already made")
def test_correction_after_accept_cleans_up_crm(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "accept")
    assert any(r["kind"] == "associate_contact" for r in svc.crm.records)
    svc.feedback(d["id"], "correct", reason="wrong_person")
    live = [r for r in svc.crm.records if r["kind"] in ("associate_contact", "create_task") and not r.get("reverted")]
    assert live == [], "CRM still says the wrong Chris Walker works at Redwood"


@pytest.mark.xfail(strict=True, reason="found 2026-10-26: exclusion is keyed on one identifier of the subject")
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
