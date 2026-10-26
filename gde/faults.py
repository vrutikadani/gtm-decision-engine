"""Demo-only fault injection. Disabled unless the service runs with demo=True.

Each fault is a counter: it fires that many times and then turns itself off, so an
injected failure is always followed by the recovery path."""
from __future__ import annotations

KNOWN = {
    "slack_fail_before_post": "Slack returns 503 before the message is posted",
    "slack_timeout_after_post": "Slack posts the message but the response is lost (timeout)",
    "crm_read_timeout": "CRM read times out while building account context",
    "enrichment_timeout": "Enrichment provider times out",
    "crash_after_crm_write": "Worker crashes after the CRM write, before state is saved",
    "llm_unsupported_claim": "Model returns a competitor mention whose quote is not in the source",
}


class Faults:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.armed: dict[str, int] = {}

    def arm(self, name: str, times: int = 1) -> None:
        if not self.enabled:
            raise PermissionError("fault injection is disabled outside demo mode")
        if name not in KNOWN:
            raise KeyError(name)
        self.armed[name] = self.armed.get(name, 0) + times

    def fire(self, name: str) -> bool:
        if self.armed.get(name, 0) > 0:
            self.armed[name] -= 1
            return True
        return False

    def clear(self) -> None:
        self.armed.clear()
