"""GTM brief: what changed in the field, with every claim traceable to a conversation.

Pipeline:  raw conversations -> quarantine suspicious text -> model extracts mentions
           -> code validates each mention against the source -> code counts and compares
           windows -> code writes claims -> every claim carries citations.

The model never produces a number and never writes a claim. It only finds mentions,
and a mention whose quote is not literally in the source is rejected."""
from __future__ import annotations

import json
import re
from datetime import timedelta

from .. import audit
from ..clock import fmt, parse
from ..llm.provider import COMPETITORS

INJECTION = re.compile(r"ignore (all |any |previous |prior )*instructions|^\s*system\s*:|you are now|"
                       r"mark .{0,40} as tier", re.I)


def quarantine(conv: dict):
    kept, held = [], []
    for i, u in enumerate(conv["utterances"]):
        (held if INJECTION.search(u["text"]) else kept).append((i, u))
    return kept, held


def validate_mention(m: dict, conv: dict, kept_idx: set[int]) -> str | None:
    """Return a rejection reason, or None if the mention is supported by the source."""
    if not isinstance(m, dict) or m.get("competitor") not in COMPETITORS:
        return "unknown competitor"
    i = m.get("utterance_index")
    if not isinstance(i, int) or i not in kept_idx:
        return "utterance index not in (non-quarantined) source"
    if not m.get("quote") or m["quote"] not in conv["utterances"][i]["text"]:
        return "quote not found verbatim in source"
    return None


def build(store, clock, llm, cfg: dict) -> dict:
    days = cfg["window_days"]
    now = clock.now()
    cur_start, prior_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    convs = [c for c in store.docs("SELECT doc FROM conversations ORDER BY date") if parse(c["date"]) >= prior_start]
    evidence, rejected, quarantined, windows = [], [], [], {"current": [], "prior": []}
    for c in convs:
        window = "current" if parse(c["date"]) >= cur_start else "prior"
        windows[window].append(c["id"])
        kept, held = quarantine(c)
        for i, u in held:
            quarantined.append({"conversation_id": c["id"], "utterance_index": i, "text": u["text"],
                                "reason": "looks like instructions to an AI, not conversation content"})
            audit.log(store, clock, "content_quarantined", None, conversation=c["id"], utterance=i)
        model_view = {**c, "utterances": [u if idx in {k for k, _ in kept} else {**u, "text": "[quarantined]"}
                                          for idx, u in enumerate(c["utterances"])]}
        raw = llm.extract_mentions(model_view)
        store.x("INSERT INTO llm_calls VALUES(?,?,?,?)", (store.next_id("LLM"), None, "extract_mentions",
                json.dumps({"provider": llm.name, "model": llm.model, "input": c["id"], "output_count": len(raw)})))
        kept_idx = {k for k, _ in kept}
        for n, m in enumerate(raw):
            why = validate_mention(m, c, kept_idx)
            if why:
                rejected.append({"conversation_id": c["id"], "mention": m, "reason": why})
                audit.log(store, clock, "unsupported_claim_rejected", None, conversation=c["id"], reason=why,
                          quote=m.get("quote"))
                continue
            u = c["utterances"][m["utterance_index"]]
            evidence.append({"id": f"M-{c['id']}-{n + 1}", "conversation_id": c["id"], "date": c["date"],
                             "window": window, "source_type": "Gong Transcript" if c["type"] == "gong_call" else "Field Note",
                             "account_id": c["account_id"], "title": c["title"], "competitor": m["competitor"],
                             "quote": m["quote"], "speaker_role": u["role"], "reason": m.get("reason")})

    claims = []
    for comp in COMPETITORS:
        cur = sorted({e["conversation_id"] for e in evidence if e["competitor"] == comp and e["window"] == "current"})
        pri = sorted({e["conversation_id"] for e in evidence if e["competitor"] == comp and e["window"] == "prior"})
        ids = [e["id"] for e in evidence if e["competitor"] == comp]
        if len(windows["current"]) < cfg["min_conversations_for_trend"]:
            continue
        direction = "increased" if len(cur) > len(pri) else "did not increase"
        claims.append({
            "id": f"CL-{comp.split()[-1]}-trend", "kind": "trend", "competitor": comp,
            "text": (f"{comp} mentions {direction}: {len(cur)} of {len(windows['current'])} conversations in the last "
                     f"{days} days, vs {len(pri)} of {len(windows['prior'])} in the {days} days before."),
            "current": len(cur), "prior": len(pri), "citations": ids})
        reasons: dict[str, list[str]] = {}
        for e in evidence:
            if e["competitor"] == comp and e["window"] == "current" and e["reason"]:
                reasons.setdefault(e["reason"], []).append(e["id"])
        if reasons and cur and max(len(v) for v in reasons.values()) >= 2:
            top, cites = max(reasons.items(), key=lambda kv: len(kv[1]))
            claims.append({"id": f"CL-{comp.split()[-1]}-reason", "kind": "reason", "competitor": comp,
                           "text": f"Most common reason in recent {comp} mentions: {top} ({len(cites)} of {len(cur)}).",
                           "citations": cites})
    # Claim gate: a claim with no resolvable citation is dropped, whoever wrote it.
    ev_ids = {e["id"] for e in evidence}
    supported = [c for c in claims if c["citations"] and set(c["citations"]) <= ev_ids]
    brief = {"id": store.next_id("BRIEF"), "created_at": clock.iso(), "window_days": days,
             "windows": {"current": {"from": fmt(cur_start), "conversations": windows["current"]},
                         "prior": {"from": fmt(prior_start), "conversations": windows["prior"]}},
             "claims": supported, "evidence": evidence, "rejected": rejected, "quarantined": quarantined,
             "model": {"provider": llm.name, "model": llm.model, "used_for": "extract_mentions only"}}
    store.x("INSERT INTO briefs VALUES(?,?,?)", (brief["id"], brief["created_at"], json.dumps(brief)))
    audit.log(store, clock, "brief_generated", None, brief=brief["id"], claims=len(supported),
              rejected=len(rejected), quarantined=len(quarantined))
    return brief
