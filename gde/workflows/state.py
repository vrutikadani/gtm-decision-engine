"""Workflow states for one signal. Transitions are an explicit table: anything not listed
is rejected and audited, so a stray click or a replayed webhook cannot move a run
somewhere it should not be."""
from __future__ import annotations

from .. import audit

TRANSITIONS: dict[str, set[str]] = {
    "RECEIVED":        {"EVALUATING", "DUPLICATE"},
    "EVALUATING":      {"DELIVER_PENDING", "NEEDS_REVIEW", "HELD", "SUPPRESSED"},
    "NEEDS_REVIEW":    {"EVALUATING", "SUPPRESSED"},
    "HELD":            {"EVALUATING"},
    "DELIVER_PENDING": {"DELIVERED", "DELIVERY_FAILED"},
    "DELIVERY_FAILED": {"DELIVER_PENDING"},
    "DELIVERED":       {"ACCEPTED", "SNOOZED", "DISMISSED", "CORRECTED"},
    "ACCEPTED":        {"EXECUTED", "CORRECTED"},
    "SNOOZED":         {"DELIVER_PENDING", "EVALUATING"},
    "CORRECTED":       {"EVALUATING"},
    "DISMISSED":       set(),
    "EXECUTED":        set(),
    "SUPPRESSED":      {"EVALUATING"},
    "DUPLICATE":       set(),
}

TERMINAL = {k for k, v in TRANSITIONS.items() if not v}


class InvalidTransition(Exception):
    pass


def transition(store, clock, run_id: str, to_state: str, reason: str) -> None:
    run = store.one("SELECT state FROM runs WHERE id=?", (run_id,))
    current = run["state"]
    if to_state not in TRANSITIONS.get(current, set()):
        audit.log(store, clock, "invalid_transition_rejected", run_id, frm=current, to=to_state, reason=reason)
        raise InvalidTransition(f"{current} -> {to_state} is not allowed")
    seq = store.one("SELECT COUNT(*) AS n FROM transitions WHERE run_id=?", (run_id,))["n"] + 1
    store.x("INSERT INTO transitions VALUES(?,?,?,?,?,?)", (run_id, seq, current, to_state, clock.iso(), reason))
    store.x("UPDATE runs SET state=?, updated_at=? WHERE id=?", (to_state, clock.iso(), run_id))
    audit.log(store, clock, "state_transition", run_id, frm=current, to=to_state, reason=reason)


def history(store, run_id: str) -> list[dict]:
    return store.all("SELECT seq, from_state, to_state, at, reason FROM transitions WHERE run_id=? ORDER BY seq", (run_id,))
