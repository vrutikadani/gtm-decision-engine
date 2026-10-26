"""Scenario 6: the hardest real failure found while building this, before and after.

BEFORE is a capture from the pre-fix commit (hardest_failure_before.json), not a
re-enactment: the old code path no longer exists. AFTER runs live on the current code."""
from __future__ import annotations

import json
from pathlib import Path

BEFORE = json.loads((Path(__file__).parent / "hardest_failure_before.json").read_text())


def run(svc) -> dict:
    e = svc.event("S5")
    d = svc.job_change(e["provider"], e["payload"])
    acc = svc.feedback(d["id"], "accept")
    cor = svc.feedback(d["id"], "correct", reason="wrong_person")
    after_crm = svc.crm.records
    still_wrong = [r for r in after_crm if r["kind"] in ("associate_contact", "create_task") and not r.get("reverted")]
    return {
        "decision_id": d["id"],
        "summary": "A seller accepts a recommendation, then finds out it was the wrong person. The correction "
                   "stopped future recommendations, but did not undo what the accepted one had already written to the CRM.",
        "before": {"source": "captured from the pre-fix commit", "crm_after_correction": BEFORE["crm_after_correction"],
                   "wrong_records_left": [r for r in BEFORE["crm_after_correction"]
                                          if r["kind"] in ("associate_contact", "create_task")]},
        "after": {"source": "live, current code", "accept_effects": acc["effects"], "correct_effects": cor["effects"],
                  "rerun_outcome": cor["rerun"]["outcome"], "crm_after_correction": after_crm,
                  "wrong_records_left": still_wrong},
        "regression_tests": ["tests/test_adversarial.py::test_correction_after_accept_cleans_up_crm",
                             "tests/test_adversarial.py::test_correction_after_a_crashed_writeback_still_cleans_up",
                             "tests/test_adversarial.py::test_wrong_play_cancels_the_task_but_keeps_the_true_association"],
    }
