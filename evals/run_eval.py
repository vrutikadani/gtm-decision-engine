"""Evaluation harness.

Identity resolution (labeled cases in identity_cases.jsonl), graded by consequence:
    correct   right person MATCHed, NO_MATCH when nobody matches, REVIEW when truly ambiguous
    safe      REVIEW when the answer was knowable (a person spends a minute; nobody is misled)
    miss      NO_MATCH for a real person (a lost opportunity, nobody is misled)
    critical  MATCH to the wrong person, or MATCH when it is nobody we know

Decisions (decision_cases.json): end-to-end outcome and play for each case.
Briefs: hand-labeled counts, citation integrity, injection and hallucination handling.

Exit code 1 on any critical identity result not tagged known_limitation, any wrong
decision, or any brief check failing. Known limitations are printed, never hidden.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gde.champions.resolution import resolve  # noqa: E402
from gde.providers.job_change import JobChange, subject_keys  # noqa: E402
from gde.service import Service  # noqa: E402

HERE = Path(__file__).parent


def grade(status, person, truth):
    if status == "MATCH":
        return "correct" if person == truth else "critical"
    if status == "REVIEW":
        return "correct" if truth == "AMBIGUOUS" else "safe"
    return "correct" if truth in (None, "AMBIGUOUS") else "miss"


def identity(svc) -> tuple[list[dict], dict]:
    rows = []
    for line in (HERE / "identity_cases.jsonl").read_text().splitlines():
        case = json.loads(line)
        s = case["signal"]
        jc = JobChange(provider="eval", provider_event_id=case["id"], name=s["name"], profile_url=s["profile_url"],
                       metro=s["metro"], new_company="", new_domain=s["new_domain"], new_title=s["new_title"],
                       previous_company=s["previous_company"], detected_at="2026-10-15T00:00:00Z")
        r = resolve(svc.store, jc, svc.cfg["identity"], subject_keys(jc))
        g = grade(r["status"], r["person_id"], case["truth"])
        rows.append({"id": case["id"], "note": case["note"], "truth": case["truth"], "status": r["status"],
                     "person": r["person_id"], "confidence": r["confidence"], "grade": g,
                     "known_limitation": case.get("known_limitation")})
    counts = {k: sum(1 for r in rows if r["grade"] == k) for k in ("correct", "safe", "miss", "critical")}
    return rows, counts


def decisions(svc) -> list[dict]:
    out = []
    for case in json.loads((HERE / "decision_cases.json").read_text()):
        svc.reset()
        for sql in case.get("setup_sql", []):
            svc.store.x(sql)
        e = svc.event(case["event"])
        e["payload"].update(case.get("payload_changes", {}))
        d = svc.job_change(e["provider"], e["payload"])
        ok = d.get("outcome") == case["expect"]["outcome"] and d.get("play") == case["expect"].get("play")
        out.append({"id": case["id"], "note": case["note"], "expected": case["expect"],
                    "got": {"outcome": d.get("outcome"), "play": d.get("play")}, "ok": ok})
    return out


def briefs(svc) -> list[dict]:
    svc.reset()
    b = svc.build_brief()
    label = json.loads((HERE / "brief_labels.json").read_text())
    ev = {e["id"]: e for e in b["evidence"]}
    convs = {c["id"]: c for c in svc.data()["conversations"]}
    checks = []
    for comp, want in label["mentions"].items():
        c = next(x for x in b["claims"] if x["competitor"] == comp and x["kind"] == "trend")
        checks.append({"check": f"{comp} counts prior/current = {want}", "ok": [c["prior"], c["current"]] == want})
    verbatim = all(ev[x]["quote"] in " ".join(u["text"] for u in convs[ev[x]["conversation_id"]]["utterances"])
                   for c in b["claims"] for x in c["citations"])
    checks.append({"check": "every citation quote appears verbatim in its source", "ok": verbatim})
    checks.append({"check": "injected instructions quarantined",
                   "ok": [q["conversation_id"] for q in b["quarantined"]] == label["quarantined"]})
    svc.reset()
    svc.faults.arm("llm_unsupported_claim")
    b2 = svc.build_brief()
    checks.append({"check": "fabricated quote rejected and does not change counts",
                   "ok": len(b2["rejected"]) == 1 and [c["text"] for c in b2["claims"]] == [c["text"] for c in b["claims"]]})
    return checks


def main() -> int:
    svc = Service()
    rows, counts = identity(svc)
    n = len(rows)
    print(f"Identity resolution: {n} labeled cases")
    for r in rows:
        flag = {"correct": " ", "safe": "~", "miss": "-", "critical": "!"}[r["grade"]]
        print(f"  {flag} {r['id']} {r['status']:<8} {str(r['person']):<6} truth={str(r['truth']):<9} "
              f"{r['confidence']:.2f}  {r['note']}")
    matches = [r for r in rows if r["status"] == "MATCH"]
    print(f"  correct {counts['correct']}, safe {counts['safe']}, miss {counts['miss']}, critical {counts['critical']}")
    print(f"  MATCH precision {sum(r['grade'] == 'correct' for r in matches)}/{len(matches)}; "
          f"sent to review {sum(r['status'] == 'REVIEW' for r in rows)}/{n}")
    known = [r for r in rows if r["grade"] == "critical" and r["known_limitation"]]
    for r in known:
        print(f"  known limitation {r['id']}: {r['known_limitation']}")
    blocking = [r for r in rows if r["grade"] == "critical" and not r["known_limitation"]]

    dec = decisions(svc)
    print(f"\nDecisions: {sum(d['ok'] for d in dec)}/{len(dec)} as expected")
    for d in dec:
        print(f"  {'ok' if d['ok'] else 'XX'} {d['id']} {d['got']['outcome']:<12} {str(d['got']['play']):<36} {d['note']}")

    br = briefs(svc)
    print(f"\nGTM brief: {sum(c['ok'] for c in br)}/{len(br)} checks")
    for c in br:
        print(f"  {'ok' if c['ok'] else 'XX'} {c['check']}")

    failed = bool(blocking) or not all(d["ok"] for d in dec) or not all(c["ok"] for c in br)
    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
