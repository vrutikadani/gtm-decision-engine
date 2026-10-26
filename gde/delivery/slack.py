"""Slack delivery adapter (simulated).

Slack has no idempotency key on chat.postMessage. A timeout is ambiguous: the message
may or may not have posted. So every message carries our decision id in message
metadata, and before a retry the adapter looks for it (conversations.history on the
channel) instead of posting blind."""
from __future__ import annotations


class SlackError(Exception):
    pass


class SlackTimeout(SlackError):
    pass


class SimulatedSlack:
    def __init__(self, clock, faults):
        self.clock, self.faults = clock, faults
        self.messages: list[dict] = []
        self.api_calls = 0

    def find_by_metadata(self, channel: str, key: str):
        self.api_calls += 1
        return next((m for m in self.messages if m["channel"] == channel and m["metadata"]["gde_key"] == key), None)

    def post(self, channel: str, blocks: dict, key: str) -> dict:
        self.api_calls += 1
        if self.faults.fire("slack_fail_before_post"):
            raise SlackError("503 service_unavailable")
        msg = {"ts": f"{1760976000 + len(self.messages)}.000100", "channel": channel, "blocks": blocks,
               "metadata": {"event_type": "gde_decision", "gde_key": key}, "at": self.clock.iso()}
        self.messages.append(msg)
        if self.faults.fire("slack_timeout_after_post"):
            raise SlackTimeout("timed out waiting for chat.postMessage response")
        return msg
