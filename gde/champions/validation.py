"""Champion validation: did this person actually champion us, or did they just attend a
webinar? CONFIRMED needs at least two independent kinds of evidence, one of them
first-party (our own product usage or CRM project/deal records), within the lookback."""
from __future__ import annotations

SOURCE_LABEL = {"warehouse": "Warehouse Usage", "crm": "CRM Record", "field_note": "Field Note", "gong": "Gong Transcript"}


def validate(store, clock, person_id: str, cfg: dict) -> dict:
    ev = store.docs("SELECT doc FROM champion_evidence WHERE person_id=? ORDER BY id", (person_id,))
    used, stale = [], []
    for e in ev:
        age = clock.days_since(e["observed_at"])
        (used if age <= cfg["evidence_max_age_days"] else stale).append({**e, "age_days": round(age)})
    types = sorted({e["type"] for e in used})
    first_party = any(e["first_party"] for e in used)
    if len(types) >= cfg["confirmed_min_types"] and (first_party or not cfg["confirmed_requires_first_party"]):
        status = "CONFIRMED"
    elif used:
        status = "WEAK"
    else:
        status = "NONE"
    sources = [{"source_type": SOURCE_LABEL.get(e["source"], e["source"]), "record_id": e["record_id"],
                "timestamp": e["observed_at"], "freshness_days": e["age_days"], "evidence": e["detail"],
                "confidence": None} for e in used]
    return {"status": status, "types": types, "first_party": first_party, "evidence": used,
            "stale_evidence": stale, "sources": sources}
