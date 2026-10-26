"""The headless system. The FastAPI app (api.py) and the in-browser demo (bridge.py)
are both thin clients of this class; neither contains business logic."""
from __future__ import annotations

import copy
import json

from . import audit
from .briefs import service as briefs
from .clock import Clock
from .decisions.engine import Engine
from .delivery import worker
from .delivery.slack import SimulatedSlack
from .faults import KNOWN as FAULTS, Faults
from .feedback import service as feedback
from .llm.provider import get_provider
from .providers.crm import SimulatedCRM
from .providers.enrichment import Enrichment
from .store import Store, load_json
from .workflows import state


class NotFound(KeyError):
    pass


class Service:
    def __init__(self, db: str = ":memory:", demo: bool = True):
        self.demo = demo
        self.world = load_json("fixtures/world.json")
        self.cfg = load_json("config/thresholds.json")
        self.plays = load_json("config/plays.json")["plays"]
        self.precedence = load_json("config/precedence.json")
        self.store = Store(db)
        self.faults = Faults(enabled=demo)
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self) -> dict:
        self.clock = Clock(self.world["demo_now"])
        self.faults.clear()
        self.store.reset(self.world)
        self.crm = SimulatedCRM(self.store, self.clock, self.faults)
        self.slack = SimulatedSlack(self.clock, self.faults)
        self.enrichment = Enrichment(self.store, self.clock, self.faults)
        self.llm = get_provider(self.faults)
        self.engine = Engine(self.store, self.clock, self.crm, self.enrichment, self.llm, self.cfg, self.plays,
                             self.precedence)
        audit.log(self.store, self.clock, "demo_reset")
        return {"ok": True, "now": self.clock.iso(), "llm": self.llm.name}

    # ---------------------------------------------------------------- signals
    def job_change(self, provider: str, payload: dict) -> dict:
        out = self.engine.ingest(provider, payload)
        worker.process(self)
        return self._fresh(out)

    def _fresh(self, out: dict) -> dict:
        if "id" in out:  # a decision: return it with the run's current state
            return {**out, "state": self.store.one("SELECT state FROM runs WHERE id=?", (out["run_id"],))["state"]}
        return out

    def retry(self, run_id: str) -> dict:
        r = self.store.one("SELECT state FROM runs WHERE id=?", (run_id,))
        if not r:
            raise NotFound(run_id)
        if r["state"] != "HELD":
            raise state.InvalidTransition(f"only HELD runs can be retried (run is {r['state']})")
        out = self.engine.evaluate(run_id)
        worker.process(self)
        return self._fresh(out)

    # --------------------------------------------------------------- decisions
    def decision(self, decision_id: str) -> dict:
        d = self.store.doc("decisions", decision_id)
        if not d:
            raise NotFound(decision_id)
        return self._fresh(d)

    def decisions(self) -> list[dict]:
        out = []
        for d in self.store.docs("SELECT doc FROM decisions ORDER BY id DESC"):
            st = self.store.one("SELECT state FROM runs WHERE id=?", (d["run_id"],))["state"]
            latest = self.store.one("SELECT id FROM decisions WHERE run_id=? ORDER BY id DESC LIMIT 1", (d["run_id"],))["id"]
            out.append({"id": d["id"], "run_id": d["run_id"], "outcome": d["outcome"], "reason": d["reason"],
                        "person": d["signal"]["name"], "account": d["signal"]["new_company"], "play": d["play"],
                        "state": st if latest == d["id"] else "SUPERSEDED", "created_at": d["created_at"]})
        return out

    def trace(self, decision_id: str) -> dict:
        d = self.decision(decision_id)
        return {"decision_id": d["id"], "outcome": d["outcome"], "reason": d["reason"], "steps": d["trace"]}

    def inspect(self, decision_id: str) -> dict:
        s = self.store
        d = self.decision(decision_id)
        sig = s.one("SELECT * FROM signals WHERE id=(SELECT signal_id FROM runs WHERE id=?)", (d["run_id"],))
        ctx_step = next(x for x in d["trace"] if x["step"] == "context")
        outbox = s.all("SELECT * FROM outbox WHERE decision_id=? ORDER BY id", (decision_id,))
        for o in outbox:
            o["doc"] = json.loads(o["doc"])
        return {
            "decision_id": decision_id, "run_id": d["run_id"],
            "inputs": {"provider": sig["provider"], "raw_payload": json.loads(sig["doc"])["raw"],
                       "normalized": d["signal"], "subject_key": d["subject_key"]},
            "context": {"status": ctx_step["status"], "detail": ctx_step["detail"], **ctx_step["data"]},
            "evidence": d["sources"],
            "rules": [{"step": x["label"], "status": x["status"], "rule": x["rule"], "detail": x["detail"]} for x in d["trace"]],
            "model": {"used": bool(d["llm_calls"]), "calls": d["llm_calls"],
                      "boundary": "labels prospect intent and drafts one sentence of copy; never chooses identity, play, owner or writes"},
            "state": {"current": self._fresh(d)["state"], "transitions": state.history(s, d["run_id"])},
            "output": {"outcome": d["outcome"], "reason": d["reason"], "surface": d["surface"]},
            "side_effects": {"outbox": outbox,
                             "slack": [m for m in self.slack.messages if m["metadata"]["gde_key"].startswith(decision_id)],
                             "crm": [r for r in self.crm.records if r["gde_key"].startswith(decision_id)]},
            "feedback": s.docs("SELECT doc FROM feedback WHERE decision_id=? ORDER BY id", (decision_id,)),
            "audit": audit.recent(s, 100, d["run_id"]),
        }

    # ---------------------------------------------------------------- feedback
    def feedback(self, decision_id: str, action: str, **kw) -> dict:
        return feedback.submit(self, decision_id, action, **kw)

    def advance(self, days: float) -> dict:
        self.clock.advance(days=days)
        woke = feedback.wake_snoozed(self)
        worker.process(self)
        return {"now": self.clock.iso(), "resurfaced": woke}

    # ----------------------------------------------------------------- reviews
    def reviews(self, status: str = "open") -> list[dict]:
        rows = self.store.all("SELECT * FROM review_queue WHERE status=? ORDER BY id", (status,))
        return [{"id": r["id"], "run_id": r["run_id"], "status": r["status"], **json.loads(r["doc"])} for r in rows]

    def resolve_review(self, review_id: str, choice: str, reviewer: str = "revops") -> dict:
        s = self.store
        r = s.one("SELECT * FROM review_queue WHERE id=?", (review_id,))
        if not r:
            raise NotFound(review_id)
        if r["status"] != "open":
            raise state.InvalidTransition("review already resolved")
        doc = json.loads(r["doc"])
        live = [c["person_id"] for c in doc["candidates"] if not c.get("excluded")]
        if choice != "none" and choice not in live:
            raise ValueError(f"choice must be one of {live} or 'none'")
        with s.tx():
            s.x("UPDATE review_queue SET status='resolved', doc=? WHERE id=?",
                (json.dumps({**doc, "choice": choice, "reviewer": reviewer, "resolved_at": self.clock.iso()}), review_id))
            if choice == "none":
                subject = s.one("SELECT subject_key FROM signals WHERE id=(SELECT signal_id FROM runs WHERE id=?)",
                                (r["run_id"],))["subject_key"]
                for pid in live:
                    s.x("INSERT OR REPLACE INTO identity_exclusions VALUES(?,?,?,?)",
                        (subject, pid, self.clock.iso(), f"reviewer {reviewer}: none of the candidates"))
                state.transition(s, self.clock, r["run_id"], "SUPPRESSED", f"reviewer {reviewer}: no candidate matches")
                audit.log(s, self.clock, "review_resolved", r["run_id"], review=review_id, choice="none")
                return {"review_id": review_id, "state": "SUPPRESSED"}
            audit.log(s, self.clock, "review_resolved", r["run_id"], review=review_id, choice=choice)
        out = self.engine.evaluate(r["run_id"], review={"person_id": choice, "reviewer": reviewer})
        worker.process(self)
        return self._fresh(out)

    # ------------------------------------------------------------------ briefs
    def build_brief(self) -> dict:
        with self.store.tx():
            return briefs.build(self.store, self.clock, self.llm, self.cfg["brief"])

    def latest_brief(self) -> dict:
        b = self.store.docs("SELECT doc FROM briefs ORDER BY id DESC LIMIT 1")
        return b[0] if b else self.build_brief()

    # -------------------------------------------------------------- champions
    def champion(self, person_id: str) -> dict:
        from .champions.validation import validate
        p = self.store.doc("people", person_id)
        if not p:
            raise NotFound(person_id)
        return {"person": p, "validation": validate(self.store, self.clock, person_id, self.cfg["champion"])}

    # ------------------------------------------------------------- explorers
    def data(self) -> dict:
        s = self.store
        return {
            "accounts": s.docs("SELECT doc FROM accounts ORDER BY id"),
            "people": s.docs("SELECT doc FROM people ORDER BY id"),
            "employment": s.docs("SELECT doc FROM employment"),
            "champion_evidence": s.docs("SELECT doc FROM champion_evidence ORDER BY id"),
            "opportunities": s.docs("SELECT doc FROM opportunities ORDER BY id"),
            "conversations": s.docs("SELECT doc FROM conversations ORDER BY date"),
            "signals": [{"id": r["id"], "provider": r["provider"], "event": r["provider_event_id"],
                         "subject_key": r["subject_key"], **json.loads(r["doc"])["normalized"]}
                        for r in s.all("SELECT * FROM signals ORDER BY id")],
            "plays": self.plays,
            "decisions": self.decisions(),
            "feedback": s.docs("SELECT doc FROM feedback ORDER BY id"),
            "identity_exclusions": s.all("SELECT * FROM identity_exclusions"),
            "suppressions": s.all("SELECT * FROM suppressions"),
            "crm_records": self.crm.records,
            "slack_messages": self.slack.messages,
        }

    def reliability(self) -> dict:
        s = self.store
        kinds = {r["kind"]: r["n"] for r in s.all("SELECT kind, COUNT(*) n FROM audit GROUP BY kind")}
        health = {}
        for name, evts in {"slack": ["slack_attempt_failed"], "crm": ["context_unavailable", "worker_crashed"],
                           "enrichment": ["enrichment_cache_used"], "llm": ["unsupported_claim_rejected"]}.items():
            n = sum(kinds.get(e, 0) for e in evts)
            health[name] = {"recent_errors": n, "status": "degraded" if n else "ok"}
        return {
            "failed_workflows": s.all("SELECT id, state, updated_at FROM runs WHERE state IN ('DELIVERY_FAILED')"),
            "held": s.all("SELECT id, state, updated_at FROM runs WHERE state='HELD'"),
            "retries": s.all("SELECT id, decision_id, kind, status, attempts, last_error FROM outbox WHERE attempts > 1 OR last_error IS NOT NULL"),
            "review_queue": self.reviews(),
            "duplicates_suppressed": kinds.get("duplicate_suppressed", 0) + s.one("SELECT COUNT(*) n FROM runs WHERE state='DUPLICATE'")["n"],
            "unsupported_claims_rejected": kinds.get("unsupported_claim_rejected", 0),
            "content_quarantined": kinds.get("content_quarantined", 0),
            "invalid_transitions_rejected": kinds.get("invalid_transition_rejected", 0),
            "stale_signals_suppressed": sum(1 for d in s.docs("SELECT doc FROM decisions")
                                            if any(x["step"] == "freshness" and x["status"] == "FAIL" for x in d["trace"])),
            "provider_health": health,
            "recent_audit": audit.recent(s, 40),
        }

    # ------------------------------------------------------------------- demo
    def _demo_only(self):
        if not self.demo:
            raise PermissionError("demo endpoints are disabled")

    def event(self, key: str) -> dict:
        return copy.deepcopy(self.world["events"][key])

    def run_scenario(self, n: int) -> dict:
        from .demo import scenarios
        self._demo_only()
        return scenarios.run(self, n)

    def inject(self, name: str) -> dict:
        from .demo import failures
        self._demo_only()
        return failures.run(self, name)

    def faults_list(self) -> dict:
        from .demo import failures
        return {"faults": FAULTS, "injections": failures.CATALOG}
