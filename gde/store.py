"""SQLite persistence. One file locally, in-memory in the browser demo.

Reference data (accounts, people, evidence...) is loaded from fixtures on reset.
Operational data (signals, runs, decisions, feedback, outbox, audit) is written by
the engine. Every write that must happen together goes through `tx()`.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS reps(id TEXT PRIMARY KEY, doc TEXT);
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, domain TEXT UNIQUE, doc TEXT);
CREATE TABLE IF NOT EXISTS enrichment(domain TEXT PRIMARY KEY, doc TEXT);
CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY, doc TEXT);
CREATE TABLE IF NOT EXISTS employment(person_id TEXT, account_id TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS champion_evidence(id TEXT PRIMARY KEY, person_id TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, account_id TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, account_id TEXT, date TEXT, doc TEXT);

CREATE TABLE IF NOT EXISTS signals(
  id TEXT PRIMARY KEY, provider TEXT, provider_event_id TEXT, subject_key TEXT, move_key TEXT,
  received_at TEXT, doc TEXT, UNIQUE(provider, provider_event_id));
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, signal_id TEXT, state TEXT, updated_at TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS transitions(run_id TEXT, seq INTEGER, from_state TEXT, to_state TEXT, at TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, run_id TEXT, created_at TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS review_queue(id TEXT PRIMARY KEY, run_id TEXT, status TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, decision_id TEXT, at TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS identity_exclusions(subject_key TEXT, person_id TEXT, at TEXT, reason TEXT,
  PRIMARY KEY(subject_key, person_id));
CREATE TABLE IF NOT EXISTS suppressions(id TEXT PRIMARY KEY, scope TEXT, key TEXT, until TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, decision_id TEXT, kind TEXT, status TEXT,
  attempts INTEGER, last_error TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS llm_calls(id TEXT PRIMARY KEY, run_id TEXT, purpose TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, run_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS briefs(id TEXT PRIMARY KEY, created_at TEXT, doc TEXT);
CREATE TABLE IF NOT EXISTS counters(name TEXT PRIMARY KEY, value INTEGER);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, isolation_level=None)  # explicit transactions only
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._depth = 0

    # -- transactions ---------------------------------------------------------
    @contextmanager
    def tx(self):
        """Nested-safe transaction: everything inside commits together or not at all."""
        outer = self._depth == 0
        if outer:
            self.db.execute("BEGIN")
        self._depth += 1
        try:
            yield self
            self._depth -= 1
            if outer:
                self.db.execute("COMMIT")
        except BaseException:
            self._depth -= 1
            if outer:
                self.db.execute("ROLLBACK")
            raise

    # -- helpers --------------------------------------------------------------
    def x(self, sql: str, args=()):
        return self.db.execute(sql, args)

    def one(self, sql: str, args=()):
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def all(self, sql: str, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def doc(self, table: str, id_: str):
        r = self.one(f"SELECT doc FROM {table} WHERE id=?", (id_,))
        return json.loads(r["doc"]) if r else None

    def docs(self, sql: str, args=()):
        return [json.loads(r["doc"]) for r in self.all(sql, args)]

    def next_id(self, prefix: str) -> str:
        """Deterministic ids so the same scenario produces the same ids every run."""
        r = self.one("SELECT value FROM counters WHERE name=?", (prefix,))
        n = (r["value"] if r else 0) + 1
        self.x("INSERT OR REPLACE INTO counters(name, value) VALUES(?, ?)", (prefix, n))
        return f"{prefix}-{n:04d}"

    # -- reset ----------------------------------------------------------------
    def reset(self, world: dict):
        tables = [r["name"] for r in self.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        with self.tx():
            for t in tables:
                self.x(f"DELETE FROM {t}")
            for r in world["reps"]:
                self.x("INSERT INTO reps VALUES(?,?)", (r["id"], json.dumps(r)))
            for a in world["accounts"]:
                self.x("INSERT INTO accounts VALUES(?,?,?)", (a["id"], a["domain"], json.dumps(a)))
            for e in world["enrichment"]:
                self.x("INSERT INTO enrichment VALUES(?,?)", (e["domain"], json.dumps(e)))
            for p in world["people"]:
                self.x("INSERT INTO people VALUES(?,?)", (p["id"], json.dumps(p)))
            for e in world["employment"]:
                self.x("INSERT INTO employment VALUES(?,?,?)", (e["person_id"], e["account_id"], json.dumps(e)))
            for e in world["champion_evidence"]:
                self.x("INSERT INTO champion_evidence VALUES(?,?,?)", (e["id"], e["person_id"], json.dumps(e)))
            for o in world["opportunities"]:
                self.x("INSERT INTO opportunities VALUES(?,?,?)", (o["id"], o["account_id"], json.dumps(o)))
            for c in world["conversations"]:
                self.x("INSERT INTO conversations VALUES(?,?,?,?)", (c["id"], c["account_id"], c["date"], json.dumps(c)))


def load_json(rel: str) -> dict:
    return json.loads((HERE / rel).read_text())
