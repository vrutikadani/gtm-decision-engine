"""Regressions for audit findings: outbox error handling, restart safety, model-output
validation, out-of-order events and keeping model calls out of DB transactions."""
import json

import pytest

from conftest import ev
from gde import bridge
from gde.delivery import worker
from gde.service import Service


def _outbox(svc, decision_id, kind="crm_writeback"):
    return svc.store.one("SELECT * FROM outbox WHERE decision_id=? AND kind=? ORDER BY id LIMIT 1", (decision_id, kind))


# --- 1. outbox: CRM failures are retried, capped and isolated --------------------------

def test_crm_504_on_accept_does_not_return_500(svc):
    from gde.providers.crm import CRMTimeout
    d = svc.job_change(*ev(svc, "S1"))

    def gateway_timeout(*a, **k):
        raise CRMTimeout("504 gateway timeout")
    svc.crm.upsert = gateway_timeout  # no fault hook needed: any adapter exception must be contained
    code, out = bridge.handle(svc, "POST", "/feedback", {"decision_id": d["id"], "action": "accept"})
    assert code == 200 and out["state"] == "ACCEPTED"


def test_crm_failure_does_not_block_unrelated_slack_card(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.faults.arm("crm_write_fail", 100)
    svc.feedback(d["id"], "accept")
    other = svc.job_change(*ev(svc, "S4"))
    assert other["state"] == "DELIVERED" and len(svc.slack.messages) == 2


def test_crm_writeback_dead_letters_after_max_attempts(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.faults.arm("crm_write_fail", 100)
    svc.feedback(d["id"], "accept")
    svc.faults.clear()
    row = _outbox(svc, d["id"])
    assert row["status"] == "dead" and row["attempts"] == svc.cfg["delivery_max_attempts"]
    assert "504" in row["last_error"]
    worker.process(svc)  # a dead row is not retried by later passes
    assert _outbox(svc, d["id"])["attempts"] == svc.cfg["delivery_max_attempts"]
    rel = svc.reliability()
    assert [x["id"] for x in rel["dead_letters"]] == [row["id"]]
    assert [x["id"] for x in rel["writeback_failed"]] == [d["run_id"]]
    assert "WRITEBACK_FAILED" in svc.inspect(d["id"])["state"]["flags"]


def test_crm_transient_failure_is_retried_and_written_exactly_once(svc):
    d = svc.job_change(*ev(svc, "S1"))
    svc.faults.arm("crm_write_fail", 1)
    svc.feedback(d["id"], "accept")
    row = _outbox(svc, d["id"])
    assert row["status"] == "done" and row["attempts"] == 2
    assert sorted(r["kind"] for r in svc.crm.records) == ["associate_contact", "create_task"]
    assert svc.reliability()["writeback_failed"] == []


def test_crm_compensation_failure_dead_letters_and_flags_run(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "accept")
    svc.faults.arm("crm_write_fail", 100)
    svc.feedback(d["id"], "correct", reason="wrong_person")
    svc.faults.clear()
    assert _outbox(svc, d["id"], "crm_compensate")["status"] == "dead"
    assert d["run_id"] in [x["id"] for x in svc.reliability()["writeback_failed"]]


# --- 2. persistence: a file DB survives restart; stuck runs are recovered once -----------

class Interrupted(BaseException):
    """Stands in for the process dying (OOM, deploy, kill -9)."""


def test_file_db_survives_restart_and_stuck_run_is_recovered_once(tmp_path):
    path = str(tmp_path / "gde.db")
    svc1 = Service(db=path)
    real = svc1.engine._decide

    def die(*a, **k):
        raise Interrupted()
    svc1.engine._decide = die
    with pytest.raises(Interrupted):
        svc1.job_change(*ev(svc1, "S1"))
    run_id = svc1.store.one("SELECT id FROM runs")["id"]
    assert svc1.store.one("SELECT state FROM runs WHERE id=?", (run_id,))["state"] == "EVALUATING"
    svc1.engine._decide = real
    svc1.store.db.close()

    svc2 = Service(db=path)  # restart on the same file
    assert svc2.store.one("SELECT COUNT(*) n FROM signals")["n"] == 1, "restart wiped the database"
    svc2.recover()
    svc2.recover()  # a second sweep finds nothing to do
    decisions = svc2.store.all("SELECT id FROM decisions WHERE run_id=?", (run_id,))
    assert len(decisions) == 1
    assert svc2.store.one("SELECT state FROM runs WHERE id=?", (run_id,))["state"] == "DELIVERED"
    assert len(svc2.slack.messages) == 1


def test_explicit_demo_reset_still_wipes(tmp_path):
    svc = Service(db=str(tmp_path / "gde.db"))
    svc.job_change(*ev(svc, "S1"))
    svc.reset()
    assert svc.store.one("SELECT COUNT(*) n FROM decisions")["n"] == 0


# --- 3. model output is validated before use -------------------------------------------

def test_invalid_intent_label_never_reaches_the_card(svc):
    svc.llm.classify_intent = lambda text: ("BUY_NOW!!", 5.0)
    d = svc.job_change(*ev(svc, "S4"))
    assert "BUY_NOW" not in json.dumps(d["surface"])
    conv = next(x for x in d["trace"] if x["step"] == "conversation_context")
    assert conv["status"] == "NONE"
    calls = [c for c in d["llm_calls"] if c["purpose"] == "classify_intent"]
    assert calls and not any(c["validated"] for c in calls)


def test_intent_confidence_is_clamped(svc):
    svc.llm.classify_intent = lambda text: ("evaluating", 5.0) if "evaluat" in text.lower() else ("none", -2)
    d = svc.job_change(*ev(svc, "S4"))
    intents = next(x for x in d["trace"] if x["step"] == "conversation_context")["data"]["intents"]
    assert intents and all(0 <= i["confidence"] <= 1 for i in intents)


# --- 4. out-of-order events -------------------------------------------------------------

OLDER_PRIYA_MOVE = {"event_id": "JS-0999", "person": {"full_name": "Priya Raman",
                    "profile_url": "linkedin.example/in/priya-raman-4821", "location": "Phoenix"},
                    "new_role": {"company": "Summit Skin Clinics", "domain": "summit-skin.example",
                                 "title": "Practice Director", "start_date": "2026-09-20"},
                    "previous_role": {"company": "Harbor Aesthetics"}, "detected_at": "2026-10-01T08:00:00Z"}


def test_older_move_arriving_after_newer_one_is_suppressed(svc):
    first = svc.job_change(*ev(svc, "S1"))
    assert first["outcome"] == "DELIVER"
    late = svc.job_change("jobsignal", dict(OLDER_PRIYA_MOVE))
    assert late["outcome"] == "SUPPRESS" and "newer" in late["reason"]
    assert len(svc.slack.messages) == 1
    assert svc.store.one("SELECT COUNT(*) n FROM signals")["n"] == 2  # recorded, not dropped


def test_newer_move_after_older_one_still_delivers(svc):
    svc.job_change("jobsignal", dict(OLDER_PRIYA_MOVE))
    newer = svc.job_change(*ev(svc, "S1"))
    assert newer["outcome"] == "DELIVER"


# --- 5. no model call while a DB transaction is open ------------------------------------

def test_draft_opener_runs_outside_the_db_transaction(svc):
    depths, real = [], svc.llm.draft_opener

    def spy(facts):
        depths.append(svc.store._depth)
        return real(facts)
    svc.llm.draft_opener = spy
    d = svc.job_change(*ev(svc, "S1"))
    assert d["outcome"] == "DELIVER" and depths == [0]


# --- doc-honesty follow-ups: card retraction and the optional real model ----------------

def test_correction_edits_the_already_posted_slack_card(svc):
    d = svc.job_change(*ev(svc, "S5"))
    svc.feedback(d["id"], "correct", reason="wrong_person")
    [msg] = svc.slack.messages  # edited in place, not a second message
    assert msg["blocks"]["retracted"] and "wrong_person" in msg["blocks"]["text"]
    svc.store.x("UPDATE outbox SET status='pending' WHERE kind='slack_retract'")  # replay
    worker.process(svc)
    assert len(svc.slack.messages) == 1 and "retracted" not in msg["blocks"]["original"]


def test_anthropic_draft_opener_is_validated_by_the_engine(svc, monkeypatch):
    from gde.llm.provider import AnthropicProvider, FallbackProvider, MockProvider
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    real = AnthropicProvider()
    real._call = lambda system, user: "Priya, we guarantee 40% savings vs Competitor Alpha!"
    svc.engine.llm = FallbackProvider(real, MockProvider())
    d = svc.job_change(*ev(svc, "S1"))
    call = next(c for c in d["llm_calls"] if c["purpose"] == "draft_opener")
    assert call["validated"] is False
    assert d["surface"]["suggested_opener"] == "Congrats on the new role at Northwind Dermatology Group, Priya."
