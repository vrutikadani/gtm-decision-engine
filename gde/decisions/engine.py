"""Decision engine: one job-change signal in, one auditable decision out.

    signal -> dedupe -> freshness -> identity -> champion -> account context
           -> qualification -> seller suppressions -> conversation context -> plays -> decision

Outcomes:
    DELIVER       a seller gets one card with an approved play
    NEEDS_REVIEW  a person decides (ambiguous identity, ownership in flux)
    HOLD          not now, retry later (CRM unreachable)
    SUPPRESS      nothing to do, and the trace says why

Every step writes a trace entry: the business rule that ran, what it saw, and the
result. That trace is what the UI shows under "Why did the system decide this?".
It is a record of rules and evidence, not model reasoning.
"""
from __future__ import annotations

import json
import re
import sqlite3

from .. import audit
from ..accounts.qualification import qualify
from ..briefs.service import INJECTION
from ..champions.resolution import resolve
from ..champions.validation import validate
from ..context.truth import ContextUnavailable, account_context
from ..plays.registry import evaluate as evaluate_plays
from ..providers.job_change import JobChange, move_key, normalize, subject_keys
from ..workflows import state

STEPS = ["signal", "dedupe", "freshness", "identity", "champion", "context", "qualification",
         "suppression", "conversation_context", "plays", "decision"]
LABELS = {"signal": "Job change signal", "dedupe": "Duplicate check", "freshness": "Signal freshness",
          "identity": "Person identity", "champion": "Champion status", "context": "Account context",
          "qualification": "Account qualification", "suppression": "Seller feedback / cooldowns",
          "conversation_context": "Recent conversations", "plays": "Approved play eligibility",
          "decision": "Decision"}
OUTCOME_STATE = {"DELIVER": "DELIVER_PENDING", "NEEDS_REVIEW": "NEEDS_REVIEW", "HOLD": "HELD", "SUPPRESS": "SUPPRESSED"}


class Trace:
    def __init__(self):
        self.steps: list[dict] = []
        self.sources: list[dict] = []

    def add(self, step: str, status: str, detail: str, rule: str = "", **data):
        self.steps.append({"step": step, "label": LABELS[step], "status": status, "detail": detail,
                           "rule": rule, "data": data})

    def finish(self):
        seen = {s["step"] for s in self.steps}
        for s in STEPS:
            if s not in seen:
                self.steps.append({"step": s, "label": LABELS[s], "status": "SKIPPED",
                                   "detail": "not reached", "rule": "", "data": {}})
        order = {s: i for i, s in enumerate(STEPS)}
        self.steps.sort(key=lambda s: order[s["step"]])
        return self.steps


class Engine:
    def __init__(self, store, clock, crm, enrichment, llm, cfg: dict, plays: list[dict], precedence: dict):
        self.store, self.clock, self.crm, self.enrichment, self.llm = store, clock, crm, enrichment, llm
        self.cfg, self.plays, self.precedence = cfg, plays, precedence

    # ------------------------------------------------------------------ ingest
    def ingest(self, provider: str, payload: dict) -> dict:
        try:
            return self._ingest(provider, payload)
        except sqlite3.IntegrityError:
            # two deliveries of the same webhook raced past the check; the UNIQUE
            # constraint on (provider, provider_event_id) is the real guard
            return self._ingest(provider, payload)

    def _ingest(self, provider: str, payload: dict) -> dict:
        jc = normalize(provider, payload)
        s = self.store
        with s.tx():
            prior = s.one("SELECT id FROM signals WHERE provider=? AND provider_event_id=?", (provider, jc.provider_event_id))
            if prior:
                run = s.one("SELECT id FROM runs WHERE signal_id=?", (prior["id"],))
                audit.log(s, self.clock, "duplicate_suppressed", run["id"], provider=provider,
                          provider_event_id=jc.provider_event_id, rule="same provider event id")
                return {"duplicate": True, "run_id": run["id"], "reason": "same provider event id already processed"}
            sid, run_id = s.next_id("SIG"), s.next_id("RUN")
            sk, mk = subject_keys(jc), move_key(jc)
            s.x("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", (sid, provider, jc.provider_event_id, json.dumps(sk), mk,
                self.clock.iso(), json.dumps({"normalized": jc.to_dict(), "raw": payload})))
            s.x("INSERT INTO runs VALUES(?,?,?,?,?)", (run_id, sid, "RECEIVED", self.clock.iso(), "{}"))
            audit.log(s, self.clock, "signal_received", run_id, provider=provider, event=jc.provider_event_id)
            window = self.cfg["cross_provider_dedupe_days"]
            for other in s.all("SELECT s.id, s.provider, s.received_at, r.id AS run_id, r.state FROM signals s "
                               "JOIN runs r ON r.signal_id = s.id WHERE s.move_key=? AND s.id<>?", (mk, sid)):
                if other["state"] != "DUPLICATE" and self.clock.days_since(other["received_at"]) <= window:
                    state.transition(s, self.clock, run_id, "DUPLICATE",
                                     f"same move already reported by {other['provider']} ({other['run_id']})")
                    return {"duplicate": True, "run_id": run_id, "original_run_id": other["run_id"],
                            "reason": f"same person and company reported by {other['provider']} within {window} days"}
        return self.evaluate(run_id)

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, run_id: str, review: dict | None = None) -> dict:
        s, clock, cfg = self.store, self.clock, self.cfg
        run = s.one("SELECT * FROM runs WHERE id=?", (run_id,))
        sig_row = s.one("SELECT * FROM signals WHERE id=?", (run["signal_id"],))
        sig = json.loads(sig_row["doc"])
        jc = JobChange(**sig["normalized"])
        with s.tx():
            state.transition(s, clock, run_id, "EVALUATING", "review resolved" if review else "evaluate")
        t, llm_calls = Trace(), []
        age = clock.days_since(jc.detected_at)
        t.add("signal", "RECEIVED", f"{jc.name} -> {jc.new_title} at {jc.new_company}",
              provider=jc.provider, event=jc.provider_event_id)
        t.sources.append({"source_type": "Job Change Provider", "record_id": f"{jc.provider}/{jc.provider_event_id}",
                          "timestamp": jc.detected_at, "freshness_days": round(age, 1),
                          "evidence": f"{jc.name}: {jc.previous_company or 'previous company not given'} -> {jc.new_company}",
                          "confidence": None})
        t.add("dedupe", "PASS", "first report of this event and this move", "provider event id + (name, new domain) within "
              f"{cfg['cross_provider_dedupe_days']} days")
        ctx = {"jc": jc, "age": age, "trace": t, "llm_calls": llm_calls, "run_id": run_id,
               "subject_keys": json.loads(sig_row["subject_key"])}

        outcome = self._decide(ctx, review)
        return self._persist(run_id, ctx, outcome)

    def _decide(self, c: dict, review: dict | None) -> dict:
        s, clock, cfg, t, jc = self.store, self.clock, self.cfg, c["trace"], c["jc"]

        # freshness
        if c["age"] > cfg["signal_max_age_days"]:
            t.add("freshness", "FAIL", f"detected {c['age']:.0f} days ago", f"max {cfg['signal_max_age_days']} days")
            return {"outcome": "SUPPRESS", "reason": f"Signal is {c['age']:.0f} days old; too late to act on."}
        t.add("freshness", "PASS", f"detected {c['age']:.0f} days ago", f"max {cfg['signal_max_age_days']} days")

        # identity
        ident = resolve(s, jc, cfg["identity"], c["subject_keys"])
        if review and review.get("person_id"):
            ident.update(status="MATCH", person_id=review["person_id"],
                         reason=f"confirmed by {review['reviewer']} in review", reviewed=True)
            ident["confidence"] = next((x["score"] for x in ident["candidates"] if x["person_id"] == review["person_id"]), 0)
        c["identity"] = ident
        t.add("identity", ident["status"], ident["reason"],
              f"MATCH >= {cfg['identity']['match_min']} and margin >= {cfg['identity']['min_margin']}; "
              f"REVIEW >= {cfg['identity']['review_min']}",
              confidence=ident["confidence"], candidates=ident["candidates"])
        if ident["status"] == "REVIEW":
            return {"outcome": "NEEDS_REVIEW", "queue": "identity",
                    "reason": f"Cannot tell which {jc.name} this is. A person must choose before any seller sees it."}
        if ident["status"] == "NO_MATCH":
            return {"outcome": "SUPPRESS", "reason": "Not a known contact; no champion history to act on."}
        person = s.doc("people", ident["person_id"])
        c["person"] = person
        c["previous_account"] = s.doc("accounts", person["account_id"])

        # champion
        ch = validate(s, clock, person["id"], cfg["champion"])
        c["champion"] = ch
        t.sources.extend(ch["sources"])
        t.sources.append({"source_type": "CRM Contact", "record_id": f"contact/{person['id']}", "timestamp": None,
                          "freshness_days": None, "evidence": f"{person['name']}, {person['title']} at "
                          f"{c['previous_account']['name']}; profile {person.get('profile_url') or 'none on file'}",
                          "confidence": ident["confidence"]})
        t.add("champion", ch["status"], ", ".join(e["detail"] for e in ch["evidence"]) or "no evidence",
              f">= {cfg['champion']['confirmed_min_types']} evidence types incl. first-party, within "
              f"{cfg['champion']['evidence_max_age_days']} days", types=ch["types"], evidence=ch["evidence"])
        if ch["status"] != "CONFIRMED":
            return {"outcome": "SUPPRESS", "reason": f"{person['name']} is not a confirmed champion ({ch['status']})."}

        # account context
        try:
            ctx = account_context(self.crm, self.enrichment, clock, jc.new_domain, self.precedence,
                                  cfg["context_max_age_days"])
        except ContextUnavailable as e:
            audit.log(s, clock, "context_unavailable", c["run_id"], error=str(e))
            t.add("context", "UNAVAILABLE", str(e), "CRM is the system of record; no CRM, no decision")
            return {"outcome": "HOLD", "retryable": True,
                    "reason": "CRM unreachable; cannot verify ownership or open deals. Held for retry."}
        c["context"] = ctx
        if ctx.get("enrichment_served_from") == "cache":
            audit.log(s, clock, "enrichment_cache_used", c["run_id"], domain=jc.new_domain)
        t.sources.extend(ctx["sources"])
        t.add("context", "OK" if ctx["account"] else "MISSING",
              "; ".join(ctx["notes"]) or f"{len(ctx['conflicts'])} field conflicts resolved by precedence",
              "field precedence from config/precedence.json", conflicts=ctx["conflicts"],
              enrichment=ctx.get("enrichment_served_from"))

        # qualification
        q = qualify(ctx)
        c["qualification"] = q
        t.add("qualification", "PASS" if q["status"] == "PASS" else q["status"],
              q.get("reason") or "; ".join(f"{k}: {v['detail']}" for k, v in q["checks"].items()),
              "ICP tier 1-2, contactable, owner assigned and not mid-reassignment",
              open_opportunities=q.get("open_opportunities", []))
        if q["status"] == "UNKNOWN_ACCOUNT":
            return {"outcome": "SUPPRESS", "reason": f"{jc.new_company} is not in the CRM."}
        if q["status"] == "DO_NOT_CONTACT":
            return {"outcome": "SUPPRESS", "reason": "Account is marked do-not-contact."}
        if q["status"] == "OWNERSHIP_UNCLEAR":
            return {"outcome": "NEEDS_REVIEW", "queue": "revops",
                    "reason": "Account ownership is changing; RevOps confirms the owner before anyone is told."}
        if q["status"] == "OUTSIDE_ICP":
            return {"outcome": "SUPPRESS", "reason": f"Tier {q['tier']} account is outside the ICP."}
        acct = ctx["account"]

        # seller suppressions / cooldowns
        now = clock.iso()
        active = s.all("SELECT * FROM suppressions WHERE until > ?", (now,))
        person_block = [x for x in active if x["scope"] == "person_account" and x["key"] == f"{person['id']}|{acct['id']}"]
        suppressed_plays = {x["key"].split("|")[0] for x in active
                            if x["scope"] == "play_account" and x["key"].endswith("|" + acct["id"])}
        if person_block:
            t.add("suppression", "SUPPRESSED", person_block[0]["reason"], "seller feedback is respected until it expires",
                  until=person_block[0]["until"])
            return {"outcome": "SUPPRESS", "reason": f"Seller feedback: {person_block[0]['reason']}"}
        t.add("suppression", "PASS", f"{len(suppressed_plays)} plays suppressed for this account" if suppressed_plays
              else "no active suppressions", suppressed_plays=sorted(suppressed_plays))

        # conversation context (model: bounded intent labels)
        intents = []
        for conv in s.docs("SELECT doc FROM conversations WHERE account_id=? ORDER BY date", (acct["id"],)):
            conv_age = clock.days_since(conv["date"])
            if conv_age > 30:
                continue
            for i, u in enumerate(conv["utterances"]):
                if u["role"] != "prospect":
                    continue
                if INJECTION.search(u["text"]):  # same quarantine as the brief pipeline
                    audit.log(s, clock, "content_quarantined", c["run_id"], conversation=conv["id"], utterance=i)
                    continue
                label, conf = self.llm.classify_intent(u["text"])
                c["llm_calls"].append({"purpose": "classify_intent", "provider": self.llm.name, "model": self.llm.model,
                                       "input": f"{conv['id']}#{i}", "output": {"label": label, "confidence": conf},
                                       "validated": label in {"evaluating", "pricing", "none"} and 0 <= conf <= 1})
                if label != "none" and conf >= 0.6:
                    intents.append({"label": label, "conversation_id": conv["id"], "quote": u["text"],
                                    "age_days": round(conv_age, 1), "confidence": conf, "title": conv["title"]})
                    t.sources.append({"source_type": "Gong Transcript" if conv["type"] == "gong_call" else "Field Note",
                                      "record_id": f"conversation/{conv['id']}", "timestamp": conv["date"],
                                      "freshness_days": round(conv_age, 1), "evidence": u["text"], "confidence": conf})
        c["intents"] = intents
        t.add("conversation_context", "FOUND" if intents else "NONE",
              "; ".join(f"{i['label']} ({i['conversation_id']})" for i in intents) or "no recent buying intent",
              "model labels prospect utterances; code decides what counts (confidence >= 0.6, <= 30 days)",
              intents=intents)

        # plays
        facts = {"identity": "MATCH", "champion": "CONFIRMED", "tier": q["tier"],
                 "open_opportunities": ctx["open_opportunities"], "signal_age_days": c["age"], "intents": intents}
        results = evaluate_plays(self.plays, facts, suppressed_plays)
        chosen = next((r for r in results if r["eligible"]), None)
        t.add("plays", f"{chosen['play']} = PASS" if chosen else "NONE ELIGIBLE",
              "; ".join(f"{r['play']}: {'PASS' if r['eligible'] else ', '.join(r['failed'])}" for r in results),
              "first eligible play in registry order (config/plays.json)", results=results)
        if not chosen:
            return {"outcome": "SUPPRESS", "reason": "No approved play fits this situation."}
        play = next(p for p in self.plays if p["id"] == chosen["play"])
        c["play"] = play
        # seller capacity: a card nobody has time for teaches people to ignore the channel
        opp = ctx["open_opportunities"][0] if ctx["open_opportunities"] else None
        owner = opp["owner_id"] if play["deliver_to"] == "opportunity_owner" and opp else acct["owner_id"]
        today = clock.iso()[:10]
        sent = sum(1 for d in s.docs("SELECT doc FROM decisions WHERE created_at LIKE ?", (today + "%",))
                   if d["outcome"] == "DELIVER" and (d.get("surface") or {}).get("owner", {}).get("id") == owner)
        if sent >= cfg["rep_daily_cap"]:
            t.add("decision", "HOLD", f"{owner} already received {sent} cards today", f"rep_daily_cap = {cfg['rep_daily_cap']}")
            return {"outcome": "HOLD", "retryable": True,
                    "reason": f"{owner} is at today's limit of {cfg['rep_daily_cap']} cards; held for tomorrow."}
        return {"outcome": "DELIVER", "reason": self._reason(c)}

    def _reason(self, c: dict) -> str:
        p, play = c["person"], c["play"]
        base = f"Confirmed champion from {c['previous_account']['name']} joined qualified account {c['context']['account']['name']}"
        if play["id"] == "champion_assist_open_opp":
            return base + " with an open opportunity; the deal owner should add them."
        if play["id"] == "champion_reactivation_with_context":
            return base + " that is actively evaluating; no conflicting open opportunity."
        return base + " with no conflicting active opportunity."

    # ------------------------------------------------------------------ output
    def _surface(self, c: dict, decision_id: str) -> dict:
        jc, p, acct, play = c["jc"], c["person"], c["context"]["account"], c["play"]
        opp = c["context"]["open_opportunities"][0] if c["context"]["open_opportunities"] else None
        owner_id = opp["owner_id"] if play["deliver_to"] == "opportunity_owner" and opp else acct["owner_id"]
        owner = self.store.doc("reps", owner_id)
        facts = {"first_name": p["name"].split()[0], "account": acct["name"],
                 "previous_company": c["previous_account"]["name"]}
        opener = self.llm.draft_opener(facts)
        ok = (len(opener) <= 240 and facts["first_name"] in opener and not re.search(r"\d|Competitor|guarantee", opener))
        c["llm_calls"].append({"purpose": "draft_opener", "provider": self.llm.name, "model": self.llm.model,
                               "input": facts, "output": opener, "validated": ok})
        if not ok:
            opener = f"Congrats on the new role at {acct['name']}, {facts['first_name']}."
        why_now = (f"{p['name']} started as {jc.new_title} at {acct['name']} "
                   f"(reported {c['age']:.0f} days ago). Former champion at {c['previous_account']['name']}.")
        if c["intents"]:
            i = c["intents"][0]
            why_now += f" {acct['name']} is {i['label']} right now: \"{i['quote']}\" ({i['conversation_id']})."
        evidence = [e["detail"] for e in c["champion"]["evidence"]]
        nba = play["next_best_action"].format(person=p["name"].split()[0], account=acct["name"],
                                              opportunity=opp["id"] if opp else "")
        return {"decision_id": decision_id, "account": acct["name"], "account_id": acct["id"], "tier": acct["tier"],
                "owner": owner, "who": {"person_id": p["id"], "name": p["name"], "title": jc.new_title,
                                        "previous": f"{p['title']}, {c['previous_account']['name']}"},
                "why_now": why_now, "evidence": evidence, "play": {"id": play["id"], "name": play["name"]},
                "next_best_action": nba, "suggested_opener": opener,
                "identity_confidence": c["identity"]["confidence"],
                "controls": ["accept", "execute", "snooze", "dismiss", "correct"]}

    def _persist(self, run_id: str, c: dict, out: dict) -> dict:
        s, clock = self.store, self.clock
        with s.tx():
            did = s.next_id("DEC")
            surface = self._surface(c, did) if out["outcome"] == "DELIVER" else None
            c["trace"].steps = [x for x in c["trace"].steps if x["step"] != "decision"]
            c["trace"].add("decision", out["outcome"], out["reason"])
            d = {"id": did, "run_id": run_id, "created_at": clock.iso(), "outcome": out["outcome"],
                 "reason": out["reason"], "queue": out.get("queue"), "retryable": out.get("retryable", False),
                 "signal": c["jc"].to_dict(), "subject_keys": c["subject_keys"],
                 "person_id": (c.get("person") or {}).get("id"),
                 "account_id": ((c.get("context") or {}).get("account") or {}).get("id"),
                 "play": c["play"]["id"] if c.get("play") else None,
                 "identity": {k: c["identity"][k] for k in ("status", "confidence", "margin", "reason")} if c.get("identity") else None,
                 "trace": c["trace"].finish(), "sources": c["trace"].sources, "llm_calls": c["llm_calls"],
                 "surface": surface}
            s.x("INSERT INTO decisions VALUES(?,?,?,?)", (did, run_id, d["created_at"], json.dumps(d)))
            for call in c["llm_calls"]:
                s.x("INSERT INTO llm_calls VALUES(?,?,?,?)", (s.next_id("LLM"), run_id, call["purpose"], json.dumps(call)))
            state.transition(s, clock, run_id, OUTCOME_STATE[out["outcome"]], out["reason"])
            if out["outcome"] == "DELIVER":
                channel = surface["owner"]["slack"]
                s.x("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", (s.next_id("OUT"), did, "slack", "pending", 0, None,
                    json.dumps({"channel": channel, "key": did})))
            if out["outcome"] == "NEEDS_REVIEW":
                s.x("INSERT INTO review_queue VALUES(?,?,?,?)", (s.next_id("REV"), run_id, "open", json.dumps(
                    {"decision_id": did, "queue": out["queue"], "reason": out["reason"],
                     "signal": c["jc"].to_dict(), "candidates": (c.get("identity") or {}).get("candidates", [])})))
            audit.log(s, clock, "decision", run_id, decision=did, outcome=out["outcome"], reason=out["reason"])
        return d
