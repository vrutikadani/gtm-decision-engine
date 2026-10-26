"""Interview scenarios. Each one resets the world first, so the same click gives the
same result every time, regardless of what happened in the previous run."""
from __future__ import annotations

SCENARIOS = {
    1: {"title": "Confirmed champion movement", "event": "S1",
        "show": "Signal -> identity MATCH -> champion CONFIRMED -> account PASS -> DELIVER -> Slack card. "
                "Then press Accept to see the CRM write-back."},
    2: {"title": "Ambiguous identity", "event": "S2",
        "show": "Two Jordan Morales candidates score the same. NEEDS_REVIEW; no seller sees anything until a person picks."},
    3: {"title": "GTM brief", "event": None,
        "show": "Competitor Alpha mentions rose. Click a claim to see the exact conversations behind it. "
                "One pasted email tried to instruct the model; it was quarantined."},
    4: {"title": "Pipeline generation", "event": "S4",
        "show": "Champion move + Tier 1 fit + an evaluation call 5 days ago -> one card with Why now, Who, Evidence, "
                "Play and Next best action."},
    5: {"title": "Seller correction", "event": "S5",
        "show": "The system recommends the wrong Chris Walker (our CRM had the wrong profile URL). Press Correct -> "
                "wrong_person, then replay the event: it does not come back."},
    6: {"title": "Hardest failure (before / after)", "event": None,
        "show": "See docs/FAILURE_POSTMORTEM.md."},
}


def run(svc, n: int) -> dict:
    if n not in SCENARIOS:
        raise KeyError(n)
    svc.reset()
    meta = {"scenario": n, **SCENARIOS[n]}
    if n == 3:
        b = svc.build_brief()
        return {**meta, "brief_id": b["id"]}
    if n == 6:
        from . import hardest_failure
        return {**meta, **hardest_failure.run(svc)}
    ev = svc.event(meta["event"])
    d = svc.job_change(ev["provider"], ev["payload"])
    return {**meta, "decision_id": d.get("id"), "outcome": d.get("outcome"), "state": d.get("state")}


FOLLOWUPS = {
    5: {
        "replay_same_webhook": "Vendor redelivers the same webhook",
        "other_vendor_later": "20 days later, a second vendor reports the same move with no profile URL",
    },
}


def followup(svc, n: int, name: str) -> dict:
    if name not in FOLLOWUPS.get(n, {}):
        raise KeyError(name)
    if name == "replay_same_webhook":
        e = svc.event("S5")
        out = svc.job_change(e["provider"], e["payload"])
    else:
        svc.advance(20)
        out = svc.job_change("jobsignal", {
            "event_id": "JS-5555", "person": {"full_name": "Chris Walker", "profile_url": None, "location": "San Diego"},
            "new_role": {"company": "Redwood Plastic Surgery", "domain": "redwood-ps.example", "title": "Office Manager",
                         "start_date": "2026-10-10"},
            "previous_role": {"company": "Coastal Laser Center", "title": None},
            "detected_at": svc.clock.iso()})
    return {"followup": name, "description": FOLLOWUPS[n][name], "result": out,
            "slack_messages_total": len(svc.slack.messages)}
