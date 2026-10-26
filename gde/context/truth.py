"""Context / truth layer: one view of the account, built from several sources with an
explicit precedence per field (config/precedence.json).

The CRM is the system of record for ownership, tier, lifecycle and open deals. If the
CRM cannot be read, there is no context: the engine holds the decision rather than
guess whether a deal is already open."""
from __future__ import annotations

from ..providers.crm import CRMTimeout
from ..providers.enrichment import EnrichmentTimeout


class ContextUnavailable(Exception):
    pass


def account_context(crm, enrichment, clock, domain: str, precedence: dict, max_age_days: float) -> dict:
    try:
        acct = crm.account_by_domain(domain)
    except CRMTimeout as e:
        raise ContextUnavailable(str(e)) from e
    if acct is None:
        return {"account": None, "sources": [], "conflicts": [], "notes": [f"no CRM account for {domain}"]}
    opps = crm.open_opportunities(acct["id"])

    notes, served = [], "live"
    try:
        enr, served = enrichment.get(domain)
    except EnrichmentTimeout:
        enr, served = enrichment.cached(domain), "cache"
        notes.append("enrichment provider timed out; using cached record")
    enr_age = clock.days_since(enr["fetched_at"]) if enr else None
    enr_fresh = enr is not None and enr_age <= max_age_days
    if enr is not None and not enr_fresh:
        notes.append(f"enrichment record is {enr_age:.0f} days old; ignored")

    by_source = {"crm": acct, "enrichment": {"tier": enr.get("suggested_tier"), **enr} if enr_fresh else {}}
    fields, conflicts = {}, []
    for field, order in precedence["account"].items():
        values = {s: by_source[s].get(field) for s in by_source if by_source[s].get(field) is not None}
        winner = next((s for s in order if s in values), None)
        fields[field] = {"value": values.get(winner), "source": winner}
        if len(set(map(str, values.values()))) > 1:
            conflicts.append({"field": field, "values": values, "used": winner,
                              "rule": f"{field}: {' > '.join(order)}"})

    sources = [{"source_type": "CRM Account", "record_id": f"account/{acct['id']}",
                "timestamp": acct["crm_updated_at"], "freshness_days": round(clock.days_since(acct["crm_updated_at"]), 1),
                "evidence": f"tier {acct['tier']}, owner {acct['owner_id']}, {len(opps)} open opportunities",
                "confidence": None}]
    if enr:
        sources.append({"source_type": "Account Enrichment", "record_id": f"enrichment/{domain}",
                        "timestamp": enr["fetched_at"], "freshness_days": round(enr_age, 1),
                        "evidence": f"{enr['employees']} employees, {enr['locations']} locations (served from {served})",
                        "confidence": None})
    for o in opps:
        sources.append({"source_type": "CRM Opportunity", "record_id": f"opportunity/{o['id']}",
                        "timestamp": None, "freshness_days": None,
                        "evidence": f"open, stage {o['stage']}, owner {o['owner_id']}", "confidence": None})
    return {"account": {**acct, "resolved": fields}, "open_opportunities": opps, "sources": sources,
            "conflicts": conflicts, "notes": notes, "enrichment_served_from": served}
