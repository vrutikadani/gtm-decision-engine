"""Append-only audit log. Every decision, side effect, rejection and failure lands here."""
from __future__ import annotations

import json


def log(store, clock, kind: str, run_id: str | None = None, **detail) -> None:
    store.x("INSERT INTO audit(at, kind, run_id, detail) VALUES(?,?,?,?)",
            (clock.iso(), kind, run_id, json.dumps(detail, default=str)))


def recent(store, limit: int = 50, run_id: str | None = None) -> list[dict]:
    if run_id:
        rows = store.all("SELECT * FROM audit WHERE run_id=? ORDER BY seq DESC LIMIT ?", (run_id, limit))
    else:
        rows = store.all("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,))
    for r in rows:
        r["detail"] = json.loads(r["detail"])
    return rows
