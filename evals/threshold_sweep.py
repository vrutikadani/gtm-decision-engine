"""How the identity thresholds were chosen: sweep match_min and count outcomes on the
labeled set. The rule: zero critical (outside known limitations), then fewest reviews."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_eval import identity  # noqa: E402
from gde.service import Service  # noqa: E402

svc = Service()
base = dict(svc.cfg["identity"])
print("match_min  correct safe miss critical(new)  sent_to_review")
for m in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
    svc.cfg["identity"] = {**base, "match_min": m}
    rows, c = identity(svc)
    crit_new = sum(1 for r in rows if r["grade"] == "critical" and not r["known_limitation"])
    print(f"  {m:.2f}      {c['correct']:>3}  {c['safe']:>4} {c['miss']:>4}   {c['critical']} ({crit_new})"
          f"            {sum(r['status'] == 'REVIEW' for r in rows)}")
