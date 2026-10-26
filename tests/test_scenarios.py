from conftest import ev


def test_s1_confirmed_champion_is_delivered_once(svc):
    d = svc.job_change(*ev(svc, "S1"))
    assert d["outcome"] == "DELIVER" and d["state"] == "DELIVERED"
    assert d["identity"]["status"] == "MATCH" and d["identity"]["confidence"] > 0.9
    assert d["play"] == "champion_reactivation"
    assert len(svc.slack.messages) == 1 and svc.slack.messages[0]["channel"] == "@maya"


def test_s1_accept_writes_back_to_crm(svc):
    d = svc.job_change(*ev(svc, "S1"))
    out = svc.feedback(d["id"], "accept")
    assert out["state"] == "ACCEPTED"
    kinds = sorted(r["kind"] for r in svc.crm.records)
    assert kinds == ["associate_contact", "create_task"]
    out = svc.feedback(d["id"], "execute")
    assert out["state"] == "EXECUTED"
    assert any(r["kind"] == "complete_task" for r in svc.crm.records)


def test_s2_ambiguous_identity_never_reaches_a_seller(svc):
    d = svc.job_change(*ev(svc, "S2"))
    assert d["outcome"] == "NEEDS_REVIEW" and d["surface"] is None
    assert not svc.slack.messages
    [item] = svc.reviews()
    assert {c["person_id"] for c in item["candidates"]} == {"P-501", "P-511"}


def test_s2_review_choice_resumes_the_workflow(svc):
    svc.job_change(*ev(svc, "S2"))
    [item] = svc.reviews()
    d = svc.resolve_review(item["id"], "P-501", reviewer="revops-ana")
    assert d["outcome"] == "DELIVER" and d["identity"]["reason"].startswith("confirmed by revops-ana")
    assert len(svc.slack.messages) == 1


def test_s2_review_none_suppresses_and_remembers(svc):
    svc.job_change(*ev(svc, "S2"))
    [item] = svc.reviews()
    assert svc.resolve_review(item["id"], "none")["state"] == "SUPPRESSED"
    assert len(svc.store.all("SELECT * FROM identity_exclusions")) == 2


def test_s3_brief_claims_are_cited_and_injection_is_quarantined(svc):
    b = svc.build_brief()
    trend = next(c for c in b["claims"] if c["id"] == "CL-Alpha-trend")
    assert (trend["prior"], trend["current"]) == (2, 6)
    ev_by_id = {e["id"]: e for e in b["evidence"]}
    for c in b["claims"]:
        assert c["citations"] and all(ev_by_id[x]["quote"] for x in c["citations"])
    assert [q["conversation_id"] for q in b["quarantined"]] == ["C-116"]
    assert not any(e["conversation_id"] == "C-116" for e in b["evidence"])


def test_s4_combines_champion_fit_and_conversation(svc):
    d = svc.job_change(*ev(svc, "S4"))
    assert d["play"] == "champion_reactivation_with_context"
    s = d["surface"]
    assert "evaluating" in s["why_now"] and "C-140" in s["why_now"]
    assert s["owner"]["id"] == "rep-luis" and s["who"]["name"] == "Elena Brooks"


def test_s5_wrong_person_correction_is_not_repeated_on_rerun(svc):
    d = svc.job_change(*ev(svc, "S5"))
    assert d["outcome"] == "DELIVER" and d["person_id"] == "P-502"
    out = svc.feedback(d["id"], "correct", reason="wrong_person")
    assert out["rerun"]["outcome"] == "SUPPRESS"
    assert out["rerun"]["identity"]["status"] == "NO_MATCH"
    assert any(r["kind"] == "data_quality_task" for r in svc.crm.records)
    assert len(svc.slack.messages) == 1
