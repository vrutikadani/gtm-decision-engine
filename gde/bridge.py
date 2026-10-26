"""Transport-free router. The in-browser demo calls `dispatch()` directly (Pyodide);
the FastAPI app in api.py exposes the same routes over HTTP. tests/test_api.py checks
the two route sets are identical, so the hosted demo cannot drift from the real API."""
from __future__ import annotations

import json
import re

from .feedback.service import FeedbackError
from .providers.job_change import PayloadError
from .service import NotFound, Service
from .workflows.state import InvalidTransition

ROUTES: list[tuple[str, str, callable]] = [
    ("GET", "/health", lambda s, p, b: {"ok": True, "now": s.clock.iso(), "llm": s.llm.name, "demo": s.demo}),
    ("POST", "/signals/job-change", lambda s, p, b: s.job_change(b["provider"], b["payload"])),
    ("POST", "/runs/{run_id}/retry", lambda s, p, b: s.retry(p["run_id"])),
    ("GET", "/decisions", lambda s, p, b: s.decisions()),
    ("GET", "/decisions/{decision_id}", lambda s, p, b: s.decision(p["decision_id"])),
    ("GET", "/decisions/{decision_id}/trace", lambda s, p, b: s.trace(p["decision_id"])),
    ("GET", "/decisions/{decision_id}/inspect", lambda s, p, b: s.inspect(p["decision_id"])),
    ("POST", "/feedback", lambda s, p, b: s.feedback(b["decision_id"], b["action"], reason=b.get("reason"),
                                                     days=b.get("days"), note=b.get("note"), actor=b.get("actor", "seller"))),
    ("GET", "/reviews", lambda s, p, b: s.reviews()),
    ("POST", "/reviews/{review_id}", lambda s, p, b: s.resolve_review(p["review_id"], b["choice"], b.get("reviewer", "revops"))),
    ("GET", "/champions/{person_id}", lambda s, p, b: s.champion(p["person_id"])),
    ("GET", "/briefs", lambda s, p, b: s.latest_brief()),
    ("POST", "/briefs/generate", lambda s, p, b: s.build_brief()),
    ("GET", "/data", lambda s, p, b: s.data()),
    ("GET", "/reliability", lambda s, p, b: s.reliability()),
    ("POST", "/demo/reset", lambda s, p, b: s.reset()),
    ("GET", "/demo/scenarios", lambda s, p, b: s.scenarios()),
    ("POST", "/demo/scenarios/{n}", lambda s, p, b: s.run_scenario(int(p["n"]))),
    ("POST", "/demo/scenarios/{n}/followup/{name}", lambda s, p, b: s.followup(int(p["n"]), p["name"])),
    ("GET", "/demo/failures", lambda s, p, b: s.faults_list()),
    ("POST", "/demo/failures/{name}", lambda s, p, b: s.inject(p["name"])),
    ("POST", "/demo/clock/advance", lambda s, p, b: s.advance(float(b.get("days", 1)))),
]

_COMPILED = [(m, re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$"), path, fn)
             for m, path, fn in ROUTES]

STATUS = [(NotFound, 404), (KeyError, 404), (InvalidTransition, 409), (PermissionError, 403),
          (FeedbackError, 422), (PayloadError, 422), (ValueError, 422)]


def handle(svc: Service, method: str, path: str, body: dict | None = None):
    for m, rx, _, fn in _COMPILED:
        hit = rx.match(path)
        if m == method and hit:
            try:
                return 200, fn(svc, hit.groupdict(), body or {})
            except Exception as e:  # map domain errors to HTTP-style codes
                for typ, code in STATUS:
                    if isinstance(e, typ):
                        return code, {"error": type(e).__name__, "detail": str(e).strip("'")}
                raise
    return 404, {"error": "NoRoute", "detail": f"{method} {path}"}


_svc: Service | None = None


def dispatch(method: str, path: str, body_json: str = "") -> str:
    """Entry point for the browser demo."""
    global _svc
    if _svc is None:
        _svc = Service(demo=True)
    code, out = handle(_svc, method, path, json.loads(body_json) if body_json else None)
    return json.dumps({"status": code, "body": out}, default=str)
