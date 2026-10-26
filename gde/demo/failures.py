"""Demo-only failure injection. Each entry resets the world, injects one failure into the
baseline Priya Raman flow (scenario 1) and returns what the system did about it."""
from __future__ import annotations

from ..delivery import worker
from ..workflows.state import InvalidTransition

CATALOG = {
    "duplicate_webhook": "The job-change vendor delivers the same webhook twice",
    "second_vendor_same_move": "A second vendor reports the same move three days later",
    "stale_signal": "The signal arrives 49 days after the move was detected",
    "crm_timeout": "CRM read times out while building account context",
    "enrichment_timeout": "Enrichment provider times out",
    "conflicting_ownership": "The account is mid-reassignment between two reps",
    "slack_503": "Slack returns 503 on the first attempt",
    "slack_timeout_after_post": "Slack posts the message but the response is lost",
    "crash_after_crm_write": "Worker crashes after the CRM write, before saving state",
    "invalid_transition": "Seller clicks Execute on a recommendation they never accepted",
    "unsupported_brief_claim": "Model returns a competitor quote that is not in the transcript",
    "ambiguous_person": "Two people could be the same person (scenario 2)",
}


def run(svc, name: str) -> dict:
    if name not in CATALOG:
        raise KeyError(name)
    svc.reset()
    steps, decision_id = [], None
    e = svc.event("S1")
    prov, payload = e["provider"], e["payload"]

    def log(what, result):
        steps.append({"what": what, "result": result})

    if name == "duplicate_webhook":
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("webhook JS-1001 delivered", f"{d['outcome']} -> {d['state']}")
        again = svc.job_change(prov, payload)
        log("same webhook delivered again", again["reason"])
    elif name == "second_vendor_same_move":
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("jobsignal reports Priya -> Northwind", f"{d['outcome']} -> {d['state']}")
        other = {"id": "CW-3001", "name": "Priya Raman", "linkedin": None, "from_company": "Harbor Aesthetics",
                 "to_company": "Northwind Dermatology", "to_domain": "northwind-derm.example",
                 "to_title": "Practice Director", "metro": "Phoenix", "observed": "2026-10-12T09:00:00Z"}
        out = svc.job_change("careerwire", other)
        log("careerwire reports the same move (different id, no profile URL)", out["reason"])
    elif name == "stale_signal":
        payload = {**payload, "event_id": "JS-1001-late", "detected_at": "2026-09-01T08:00:00Z"}
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("signal detected 2026-09-01 arrives now", f"{d['outcome']}: {d['reason']}")
    elif name == "crm_timeout":
        svc.faults.arm("crm_read_timeout")
        d = svc.job_change(prov, payload)
        log("CRM read times out", f"{d['outcome']}: {d['reason']}")
        d2 = svc.retry(d["run_id"]); decision_id = d2["id"]
        log("retry after CRM recovers", f"{d2['outcome']} -> {d2['state']}")
    elif name == "enrichment_timeout":
        svc.faults.arm("enrichment_timeout")
        d = svc.job_change(prov, payload); decision_id = d["id"]
        ctx = next(s for s in d["trace"] if s["step"] == "context")
        log("enrichment times out", f"context: {ctx['detail']}")
        log("decision", f"{d['outcome']} (enrichment is non-critical; CRM fields decide)")
    elif name == "conflicting_ownership":
        svc.store.x("UPDATE accounts SET doc=json_set(doc, '$.owner_pending_change', 'rep-maya -> rep-luis') WHERE id='A-100'")
        log("territory realignment moves Northwind from Maya to Luis (pending in CRM)", "account flagged")
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("signal arrives", f"{d['outcome']} ({d['queue']} queue): {d['reason']}")
    elif name == "slack_503":
        svc.faults.arm("slack_fail_before_post")
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("first post returns 503, worker retries", f"{d['state']}; messages in Slack: {len(svc.slack.messages)}")
    elif name == "slack_timeout_after_post":
        svc.faults.arm("slack_timeout_after_post")
        d = svc.job_change(prov, payload); decision_id = d["id"]
        log("post succeeds but response times out; before retrying, worker searches channel by metadata",
            f"{d['state']}; messages in Slack: {len(svc.slack.messages)}")
    elif name == "crash_after_crm_write":
        d = svc.job_change(prov, payload); decision_id = d["id"]
        svc.faults.arm("crash_after_crm_write")
        svc.feedback(d["id"], "accept")
        log("seller accepts; worker writes to CRM then crashes", f"CRM records: {len(svc.crm.records)}; outbox row still pending")
        worker.process(svc)
        log("worker restarts and replays the row (search-before-create on gde_key)",
            f"CRM records: {len(svc.crm.records)}; nothing duplicated")
    elif name == "invalid_transition":
        d = svc.job_change(prov, payload); decision_id = d["id"]
        try:
            svc.feedback(d["id"], "execute")
        except InvalidTransition as ex:
            log("seller clicks Execute without Accept", f"rejected: {ex}")
        log("run state afterwards", svc.decision(d["id"])["state"])
    elif name == "unsupported_brief_claim":
        svc.faults.arm("llm_unsupported_claim")
        b = svc.build_brief()
        for r in b["rejected"]:
            log(f"model returned a mention in {r['conversation_id']}", f"rejected: {r['reason']} ({r['mention']['quote']!r})")
        beta = next(c for c in b["claims"] if c["id"] == "CL-Beta-trend")
        log("brief after validation", beta["text"])
    elif name == "ambiguous_person":
        e2 = svc.event("S2")
        d = svc.job_change(e2["provider"], e2["payload"]); decision_id = d["id"]
        log("Jordan Morales -> Lakeside Medspa", f"{d['outcome']}: {d['reason']}")
    return {"injection": name, "description": CATALOG[name], "steps": steps, "decision_id": decision_id,
            "reliability": {k: v for k, v in svc.reliability().items() if k != "recent_audit"}}
