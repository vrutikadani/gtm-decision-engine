"""Simulated CRM (HubSpot-shaped). The engine only talks to the CRM through this adapter.

Write-backs carry an idempotency key in a custom property (`gde_key`). Before any
create, the adapter searches for that key, so a replay after a crash finds the
earlier write instead of creating a second task. Real CRMs do not dedupe for you;
this is the search-before-create pattern you have to build."""
from __future__ import annotations


class CRMTimeout(Exception):
    pass


class SimulatedCRM:
    def __init__(self, store, clock, faults):
        self.store, self.clock, self.faults = store, clock, faults
        self.records: list[dict] = []   # every object the CRM holds that we created
        self.api_calls = 0

    # reads ---------------------------------------------------------------------
    def account(self, account_id: str) -> dict:
        self.api_calls += 1
        if self.faults.fire("crm_read_timeout"):
            raise CRMTimeout("CRM read timed out after 10s")
        return self.store.doc("accounts", account_id)

    def account_by_domain(self, domain: str):
        r = self.store.one("SELECT id FROM accounts WHERE domain=?", (domain.lower(),))
        return self.account(r["id"]) if r else None

    def open_opportunities(self, account_id: str) -> list[dict]:
        return [o for o in self.store.docs("SELECT doc FROM opportunities WHERE account_id=?", (account_id,))
                if o["status"] == "open"]

    # writes --------------------------------------------------------------------
    def find(self, gde_key: str):
        self.api_calls += 1
        return next((r for r in self.records if r["gde_key"] == gde_key), None)

    def find_prefix(self, prefix: str) -> list[dict]:
        self.api_calls += 1
        return [r for r in self.records if r["gde_key"].startswith(prefix)]

    def revert(self, target_key: str, revert_key: str, reason: str) -> dict:
        """Compensating write: remove an association or cancel a task we created earlier.
        Idempotent on revert_key, like every other write."""
        existing = self.find(revert_key)
        if existing:
            return {**existing, "created": False}
        target = self.find(target_key)
        self.api_calls += 1
        action = "cancel_task" if target["kind"] == "create_task" else "remove_" + target["kind"]
        target.update(reverted=True, reverted_at=self.clock.iso(), revert_reason=reason)
        rec = {"id": f"crm-revert-{len(self.records) + 1}", "kind": "revert", "action": action,
               "gde_key": revert_key, "target": target_key, "reason": reason, "at": self.clock.iso()}
        self.records.append(rec)
        return {**rec, "created": True}

    def upsert(self, kind: str, gde_key: str, fields: dict) -> dict:
        existing = self.find(gde_key)
        if existing:
            return {**existing, "created": False}
        self.api_calls += 1
        rec = {"id": f"crm-{kind}-{len(self.records) + 1}", "kind": kind, "gde_key": gde_key,
               "at": self.clock.iso(), **fields}
        self.records.append(rec)
        return {**rec, "created": True}
