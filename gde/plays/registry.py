"""Approved play registry. A play is eligible only if every requirement holds. The
engine walks the registry in priority order and records why each play passed or failed."""
from __future__ import annotations


def evaluate(plays: list[dict], facts: dict, suppressed: set[str]) -> list[dict]:
    results = []
    for play in plays:
        req, fails = play["requires"], []
        if facts["identity"] != req.get("identity", facts["identity"]):
            fails.append(f"identity is {facts['identity']}")
        if facts["champion"] != req.get("champion", facts["champion"]):
            fails.append(f"champion is {facts['champion']}")
        if "account_tier_in" in req and facts["tier"] not in req["account_tier_in"]:
            fails.append(f"tier {facts['tier']} not in {req['account_tier_in']}")
        if "open_opportunity" in req and bool(facts["open_opportunities"]) != req["open_opportunity"]:
            fails.append("account has an open opportunity" if facts["open_opportunities"] else "no open opportunity")
        if facts["signal_age_days"] > req.get("max_signal_age_days", 1e9):
            fails.append(f"signal is {facts['signal_age_days']:.0f} days old")
        if "recent_intent_in" in req:
            hits = [i for i in facts["intents"] if i["label"] in req["recent_intent_in"]
                    and i["age_days"] <= req.get("max_conversation_age_days", 1e9)]
            if not hits:
                fails.append("no recent evaluation or pricing conversation")
        if play["id"] in suppressed:
            fails.append("suppressed by earlier seller feedback")
        results.append({"play": play["id"], "name": play["name"], "eligible": not fails, "failed": fails})
    return results
