import pytest

from conftest import ev
from gde.delivery import worker
from gde.workflows.state import InvalidTransition


def test_duplicate_webhook_is_suppressed(svc):
    svc.job_change(*ev(svc, "S1"))
    again = svc.job_change(*ev(svc, "S1"))
    assert again["duplicate"] and len(svc.slack.messages) == 1


def test_same_move_from_second_vendor_is_suppressed(svc):
    svc.job_change(*ev(svc, "S1"))
    other = {"id": "CW-9001", "name": "Priya Raman", "linkedin": None, "from_company": "Harbor Aesthetics",
             "to_company": "Northwind Dermatology", "to_domain": "northwind-derm.example", "to_title": "Practice Director",
             "metro": "Phoenix", "observed": "2026-10-12T09:00:00Z"}
    out = svc.job_change("careerwire", other)
    assert out["duplicate"] and len(svc.slack.messages) == 1


def test_stale_signal_is_suppressed(svc):
    d = svc.job_change(*ev(svc, "S1", event_id="JS-OLD", detected_at="2026-09-01T00:00:00Z"))
    assert d["outcome"] == "SUPPRESS" and "days old" in d["reason"]


def test_crm_timeout_holds_then_retry_delivers(svc):
    svc.faults.arm("crm_read_timeout")
    d = svc.job_change(*ev(svc, "S1"))
    assert d["outcome"] == "HOLD" and d["state"] == "HELD" and not svc.slack.messages
    d2 = svc.retry(d["run_id"])
    assert d2["outcome"] == "DELIVER" and len(svc.slack.messages) == 1


def test_enrichment_timeout_uses_cache_and_still_decides(svc):
    svc.faults.arm("enrichment_timeout")
    d = svc.job_change(*ev(svc, "S1"))
    assert d["outcome"] == "DELIVER"
    ctx = next(s for s in d["trace"] if s["step"] == "context")
    assert "cached" in ctx["detail"]


def test_slack_503_is_retried(svc):
    svc.faults.arm("slack_fail_before_post")
    d = svc.job_change(*ev(svc, "S1"))
    assert d["state"] == "DELIVERED" and len(svc.slack.messages) == 1


def test_slack_timeout_after_post_does_not_double_post(svc):
    svc.faults.arm("slack_timeout_after_post")
    d = svc.job_change(*ev(svc, "S1"))
    assert d["state"] == "DELIVERED" and len(svc.slack.messages) == 1


def test_slack_down_marks_delivery_failed(svc):
    svc.faults.arm("slack_fail_before_post", 5)
    d = svc.job_change(*ev(svc, "S1"))
    assert d["state"] == "DELIVERY_FAILED" and not svc.slack.messages


def test_crash_after_crm_write_replays_without_duplicates(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.faults.arm("crash_after_crm_write")
    svc.feedback(d["id"], "accept")
    assert len(svc.crm.records) == 2
    assert svc.store.one("SELECT COUNT(*) n FROM outbox WHERE status='pending'")["n"] == 1
    worker.process(svc)  # replay
    assert len(svc.crm.records) == 2
    assert svc.store.one("SELECT COUNT(*) n FROM outbox WHERE status='pending'")["n"] == 0


def test_invalid_transition_is_rejected_and_audited(svc):
    d = svc.job_change(*ev(svc, "S1"))
    with pytest.raises(InvalidTransition):
        svc.feedback(d["id"], "execute")  # cannot execute before accepting
    assert svc.reliability()["invalid_transitions_rejected"] == 1
    assert svc.decision(d["id"])["state"] == "DELIVERED"


def test_unsupported_claim_is_rejected(svc):
    svc.faults.arm("llm_unsupported_claim")
    b = svc.build_brief()
    assert len(b["rejected"]) == 1 and "verbatim" in b["rejected"][0]["reason"]
    assert next(c for c in b["claims"] if c["id"] == "CL-Beta-trend")["current"] == 1


def test_ownership_in_flux_goes_to_revops(svc):
    svc.store.x("UPDATE accounts SET doc=json_set(doc, '$.owner_pending_change', 'rep-luis') WHERE id='A-100'")
    d = svc.job_change(*ev(svc, "S1"))
    assert d["outcome"] == "NEEDS_REVIEW" and d["queue"] == "revops" and not svc.slack.messages


def test_open_opportunity_routes_to_deal_owner(svc):
    d = svc.job_change(*ev(svc, "S1", event_id="JS-SUMMIT",
                           new_role={"company": "Summit Skin Clinics", "domain": "summit-skin.example",
                                     "title": "Practice Director", "start_date": "2026-10-01"}))
    assert d["play"] == "champion_assist_open_opp" and d["surface"]["owner"]["id"] == "rep-sam"


def test_snooze_resurfaces_later(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.feedback(d["id"], "snooze", days=3)
    assert svc.advance(2)["resurfaced"] == []
    assert svc.advance(1.5)["resurfaced"] == [d["run_id"]]
    assert len(svc.slack.messages) == 2


def test_dismiss_suppresses_play_for_account(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.feedback(d["id"], "dismiss", note="already know her")
    d2 = svc.job_change(*ev(svc, "S4", event_id="JS-X", new_role={"company": "Northwind Dermatology Group",
                            "domain": "northwind-derm.example", "title": "Clinical Director", "start_date": "2026-10-01"}))
    assert d2["outcome"] == "SUPPRESS" and "No approved play" in d2["reason"]


def test_fault_injection_disabled_outside_demo():
    from gde.service import Service
    prod = Service(demo=False)
    with pytest.raises(PermissionError):
        prod.faults.arm("crm_read_timeout")
    with pytest.raises(PermissionError):
        prod.run_scenario(1)
    with pytest.raises(PermissionError):
        prod.reset()
