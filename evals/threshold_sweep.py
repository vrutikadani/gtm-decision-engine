"""How the identity thresholds were chosen: sweep match_min and count outcomes on the
labeled set. The rule: zero critical (outside known limitations), then fewest reviews.

Tuning and reporting on the same cases overstates how well the threshold generalizes.
So the cases are split deterministically (CRC32 of the case id, even -> tune, odd ->
holdout). The threshold is picked on the tune split only, and the holdout result at
that threshold is reported next to it. With 24 cases the holdout is about 12 cases:
it catches a threshold that only works on the cases it was tuned on, but it is far
too small to estimate real-world precision."""
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_eval import identity  # noqa: E402
from gde.service import Service  # noqa: E402

GRID = (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def split(case_id: str) -> str:
    return "holdout" if zlib.crc32(case_id.encode()) % 2 else "tune"


def summarize(rows: list[dict]) -> dict:
    c = {k: sum(1 for r in rows if r["grade"] == k) for k in ("correct", "safe", "miss", "critical")}
    c["critical_new"] = sum(1 for r in rows if r["grade"] == "critical" and not r["known_limitation"])
    c["review"] = sum(r["status"] == "REVIEW" for r in rows)
    c["n"] = len(rows)
    return c


def pick(results: dict) -> float:
    """Zero new critical first, then fewest reviews; on a plateau take its middle value."""
    ok = [m for m in GRID if results[m]["critical_new"] == 0]
    fewest = min(results[m]["review"] for m in ok)
    plateau = [m for m in ok if results[m]["review"] == fewest]
    return plateau[len(plateau) // 2]


def main() -> None:
    svc = Service()
    base = dict(svc.cfg["identity"])
    by_split = {"all": {}, "tune": {}, "holdout": {}}
    for m in GRID:
        svc.cfg["identity"] = {**base, "match_min": m}
        rows, _ = identity(svc)
        by_split["all"][m] = summarize(rows)
        for name in ("tune", "holdout"):
            by_split[name][m] = summarize([r for r in rows if split(r["id"]) == name])
    svc.cfg["identity"] = base

    for name in ("all", "tune", "holdout"):
        n = by_split[name][GRID[0]]["n"]
        print(f"[{name}: {n} cases]")
        print("match_min  correct safe miss critical(new)  sent_to_review")
        for m in GRID:
            c = by_split[name][m]
            print(f"  {m:.2f}      {c['correct']:>3}  {c['safe']:>4} {c['miss']:>4}   {c['critical']} ({c['critical_new']})"
                  f"            {c['review']}")
        print()
    chosen = pick(by_split["tune"])
    h = by_split["holdout"][chosen]
    print(f"picked on tune split: match_min = {chosen:.2f} (config uses {base['match_min']:.2f})")
    print(f"holdout at {chosen:.2f}: correct {h['correct']}, safe {h['safe']}, miss {h['miss']}, "
          f"critical {h['critical']} ({h['critical_new']} new), sent to review {h['review']}/{h['n']}")


if __name__ == "__main__":
    main()
