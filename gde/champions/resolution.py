"""Identity resolution: is the person in this job-change signal someone we know?

Deliberately not an LLM. A false match sends a seller to congratulate a stranger on
behalf of the company, so every point of confidence has to be explainable.

  1. candidates   - CRM contacts whose last name matches (hard constraint)
  2. constraints  - drop candidates a human already ruled out, whose profile URL
                    contradicts the signal, or who are already known at the new company
  3. evidence     - independent features combined as noisy-OR: 1 - prod(1 - w)
  4. outcome      - MATCH only if the best candidate clears match_min AND beats the
                    runner-up by min_margin. Close calls are REVIEW, never a coin flip.
"""
from __future__ import annotations

import re

from ..providers.job_change import JobChange, norm_company, norm_name

FAMILIES = [("clinical", r"clinic|nurse|injector|medical"), ("executive", r"owner|ceo|founder|president"),
            ("operations", r"operat|practice|office|manager|director|admin")]


def title_family(title: str) -> str | None:
    t = (title or "").lower()
    return next((f for f, pat in FAMILIES if re.search(pat, t)), None)


def resolve(store, jc: JobChange, cfg: dict, subject_key: str) -> dict:
    w = cfg["weights"]
    last = norm_name(jc.name).split()[-1]
    excluded = {r["person_id"]: r["reason"] for r in
                store.all("SELECT person_id, reason FROM identity_exclusions WHERE subject_key=?", (subject_key,))}
    new_acct = store.one("SELECT id FROM accounts WHERE domain=?", (jc.new_domain.lower(),))
    candidates = []
    for p in store.docs("SELECT doc FROM people"):
        if norm_name(p["name"]).split()[-1] != last:
            continue
        acct = store.doc("accounts", p["account_id"])
        c = {"person_id": p["id"], "name": p["name"], "current_account": acct["name"], "features": {}, "score": 0.0,
             "excluded": None}
        if p["id"] in excluded:
            c["excluded"] = f"ruled out earlier: {excluded[p['id']]}"
        elif jc.profile_url and p.get("profile_url") and jc.profile_url.lower() != p["profile_url"].lower():
            c["excluded"] = "profile URL contradicts signal"
        elif new_acct and p["account_id"] == new_acct["id"]:
            c["excluded"] = "already a contact at the new company"
        if c["excluded"]:
            candidates.append(c)
            continue
        f = c["features"]
        f["profile_url"] = bool(jc.profile_url and p.get("profile_url") and jc.profile_url.lower() == p["profile_url"].lower())
        f["name_exact"] = norm_name(jc.name) == norm_name(p["name"])
        f["previous_employer"] = bool(jc.previous_company) and norm_company(jc.previous_company) == norm_company(acct["name"])
        f["metro"] = bool(jc.metro) and (jc.metro or "").lower() == (p.get("metro") or "").lower()
        f["title_family"] = title_family(jc.new_title) is not None and title_family(jc.new_title) == p.get("title_family")
        miss = 1.0
        for k, hit in f.items():
            if hit:
                miss *= 1 - w[k]
        c["score"] = round(1 - miss, 3)
        candidates.append(c)

    live = sorted([c for c in candidates if not c["excluded"]], key=lambda c: c["score"], reverse=True)
    best = live[0] if live else None
    runner = live[1]["score"] if len(live) > 1 else 0.0
    margin = round(best["score"] - runner, 3) if best else 0.0
    if best and best["score"] >= cfg["match_min"] and margin >= cfg["min_margin"]:
        status = "MATCH"
        why = (f"{best['score']:.2f} >= {cfg['match_min']}; " +
               (f"margin {margin:.2f} >= {cfg['min_margin']}" if len(live) > 1 else "no other live candidate"))
    elif best and best["score"] >= cfg["review_min"]:
        if len(live) > 1 and margin < cfg["min_margin"]:
            why = f"{len(live)} candidates within {margin:.2f} of each other (min margin {cfg['min_margin']})"
        else:
            why = f"best score {best['score']:.2f} is below match threshold {cfg['match_min']}"
        status = "REVIEW"
    else:
        status = "NO_MATCH"
        why = "no candidate clears the review threshold" if live else "no remaining candidates"
    return {"status": status, "reason": why, "subject_key": subject_key, "candidates": candidates,
            "person_id": best["person_id"] if status == "MATCH" else None,
            "confidence": best["score"] if best else 0.0, "margin": margin,
            "thresholds": {k: cfg[k] for k in ("match_min", "review_min", "min_margin")}}
