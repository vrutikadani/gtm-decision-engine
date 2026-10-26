"""Account enrichment (firmographics). Bought, not built. Non-critical: if it is down,
the engine uses the cached record and says so in the trace."""
from __future__ import annotations

import json


class EnrichmentTimeout(Exception):
    pass


class Enrichment:
    def __init__(self, store, clock, faults):
        self.store, self.clock, self.faults = store, clock, faults

    def get(self, domain: str):
        """Returns (record, served_from) where served_from is 'live' or 'cache'."""
        cached = self.store.one("SELECT doc FROM enrichment WHERE domain=?", (domain,))
        rec = json.loads(cached["doc"]) if cached else None
        if self.faults.fire("enrichment_timeout"):
            raise EnrichmentTimeout("enrichment provider timed out")
        return rec, "live"

    def cached(self, domain: str):
        cached = self.store.one("SELECT doc FROM enrichment WHERE domain=?", (domain,))
        return json.loads(cached["doc"]) if cached else None
