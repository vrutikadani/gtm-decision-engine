"""Account qualification against the ICP, using CRM values (system of record)."""
from __future__ import annotations


def qualify(ctx: dict, tiers_allowed=(1, 2)) -> dict:
    a = ctx["account"]
    if a is None:
        return {"status": "UNKNOWN_ACCOUNT", "reason": ctx["notes"][0]}
    tier = a["resolved"]["tier"]["value"]
    checks = {
        "icp_tier": {"pass": tier in tiers_allowed, "detail": f"Tier {tier} (from {a['resolved']['tier']['source']})"},
        "contactable": {"pass": not a["do_not_contact"], "detail": "do-not-contact" if a["do_not_contact"] else "ok"},
        "owner_assigned": {"pass": bool(a["owner_id"]), "detail": a["owner_id"] or "unassigned"},
        "ownership_stable": {"pass": not a.get("owner_pending_change"),
                             "detail": f"reassignment pending: {a['owner_pending_change']}" if a.get("owner_pending_change") else "stable"},
    }
    if not checks["contactable"]["pass"]:
        status = "DO_NOT_CONTACT"
    elif not checks["owner_assigned"]["pass"] or not checks["ownership_stable"]["pass"]:
        status = "OWNERSHIP_UNCLEAR"
    elif not checks["icp_tier"]["pass"]:
        status = "OUTSIDE_ICP"
    else:
        status = "PASS"
    return {"status": status, "checks": checks, "tier": tier, "open_opportunities": [o["id"] for o in ctx["open_opportunities"]]}
