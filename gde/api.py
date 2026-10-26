"""HTTP API (local demo and any real deployment). Every endpoint is a thin call into the
same router the browser demo uses (bridge.handle), so behavior is identical."""
from __future__ import annotations

import os
import threading
from typing import Any, Literal, Optional

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .bridge import handle
from .service import Service

svc = Service(db=os.environ.get("GDE_DB", ":memory:"), demo=os.environ.get("GDE_DEMO", "1") == "1")
api = APIRouter()
_lock = threading.Lock()  # one process, one SQLite connection: requests run one at a time


def call(method: str, path: str, body: dict | None = None):
    with _lock:
        code, out = handle(svc, method, path, body)
    return JSONResponse(out, status_code=code)


class JobChangeIn(BaseModel):
    provider: Literal["jobsignal", "careerwire"] = Field(description="Vendor whose payload shape this is")
    payload: dict[str, Any] = Field(description="Raw vendor payload; normalized server-side")
    model_config = {"json_schema_extra": {"example": {"provider": "jobsignal", "payload": {
        "event_id": "JS-1001", "person": {"full_name": "Priya Raman", "profile_url": "linkedin.example/in/priya-raman-4821",
                                          "location": "Phoenix"},
        "new_role": {"company": "Northwind Dermatology Group", "domain": "northwind-derm.example",
                     "title": "Practice Director", "start_date": "2026-10-01"},
        "previous_role": {"company": "Harbor Aesthetics", "title": "Operations Director"},
        "detected_at": "2026-10-09T08:00:00Z"}}}}


class FeedbackIn(BaseModel):
    decision_id: str
    action: Literal["accept", "execute", "snooze", "dismiss", "correct"]
    reason: Optional[Literal["wrong_person", "wrong_play", "already_engaged", "wrong_account"]] = None
    days: Optional[int] = None
    note: Optional[str] = None
    actor: str = "seller"


class ReviewIn(BaseModel):
    choice: str = Field(description="person_id of the right candidate, or 'none'")
    reviewer: str = "revops"


class AdvanceIn(BaseModel):
    days: float = 1


@api.get("/health", tags=["system"])
def health():
    return call("GET", "/health")


@api.post("/signals/job-change", tags=["signals"], summary="Ingest a job-change webhook and decide")
def job_change(body: JobChangeIn):
    return call("POST", "/signals/job-change", body.model_dump())


@api.post("/runs/{run_id}/retry", tags=["signals"], summary="Re-evaluate a HELD run")
def retry(run_id: str):
    return call("POST", f"/runs/{run_id}/retry")


@api.get("/decisions", tags=["decisions"])
def decisions():
    return call("GET", "/decisions")


@api.get("/decisions/{decision_id}", tags=["decisions"])
def decision(decision_id: str):
    return call("GET", f"/decisions/{decision_id}")


@api.get("/decisions/{decision_id}/trace", tags=["decisions"], summary="Structured rule-and-evidence trace")
def trace(decision_id: str):
    return call("GET", f"/decisions/{decision_id}/trace")


@api.get("/decisions/{decision_id}/inspect", tags=["decisions"], summary="Inputs, context, rules, model, state, side effects")
def inspect(decision_id: str):
    return call("GET", f"/decisions/{decision_id}/inspect")


@api.post("/feedback", tags=["feedback"])
def feedback(body: FeedbackIn):
    return call("POST", "/feedback", body.model_dump())


@api.get("/reviews", tags=["review"])
def reviews():
    return call("GET", "/reviews")


@api.post("/reviews/{review_id}", tags=["review"], summary="Resolve an identity or ownership review")
def resolve_review(review_id: str, body: ReviewIn):
    return call("POST", f"/reviews/{review_id}", body.model_dump())


@api.get("/champions/{person_id}", tags=["champions"])
def champion(person_id: str):
    return call("GET", f"/champions/{person_id}")


@api.get("/briefs", tags=["briefs"], summary="Latest GTM brief (generated if none)")
def briefs():
    return call("GET", "/briefs")


@api.post("/briefs/generate", tags=["briefs"])
def generate_brief():
    return call("POST", "/briefs/generate")


@api.get("/data", tags=["demo"], summary="Synthetic dataset and operational tables")
def data():
    return call("GET", "/data")


@api.get("/reliability", tags=["system"])
def reliability():
    return call("GET", "/reliability")


@api.post("/demo/reset", tags=["demo"])
def reset():
    return call("POST", "/demo/reset")


@api.get("/demo/scenarios", tags=["demo"])
def scenarios():
    return call("GET", "/demo/scenarios")


@api.post("/demo/scenarios/{n}", tags=["demo"])
def run_scenario(n: int):
    return call("POST", f"/demo/scenarios/{n}")


@api.post("/demo/scenarios/{n}/followup/{name}", tags=["demo"])
def followup(n: int, name: str):
    return call("POST", f"/demo/scenarios/{n}/followup/{name}")


@api.get("/demo/failures", tags=["demo"], summary="DEMO ONLY: failure injection catalog")
def failures():
    return call("GET", "/demo/failures")


@api.post("/demo/failures/{name}", tags=["demo"], summary="DEMO ONLY: inject a failure")
def inject(name: str):
    return call("POST", f"/demo/failures/{name}")


@api.post("/demo/clock/advance", tags=["demo"])
def advance(body: AdvanceIn):
    return call("POST", "/demo/clock/advance", body.model_dump())


app = FastAPI(title="GTM Decision Engine", version="1.0.0",
              description="Synthetic reference implementation. No employer data or proprietary production logic.",
              docs_url="/docs")
app.include_router(api, prefix="/api")
