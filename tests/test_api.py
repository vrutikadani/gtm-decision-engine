import json

from fastapi.testclient import TestClient

from gde import bridge
from gde.api import app

client = TestClient(app)


def test_http_and_browser_expose_the_same_routes():
    http = {(m.upper(), p.removeprefix("/api")) for p, ops in app.openapi()["paths"].items() for m in ops}
    browser = {(m, p) for m, p, _ in bridge.ROUTES}
    assert http == browser


def test_http_flow_end_to_end():
    client.post("/api/demo/reset")
    r = client.post("/api/demo/scenarios/1").json()
    d = client.get(f"/api/decisions/{r['decision_id']}/trace").json()
    assert d["outcome"] == "DELIVER" and d["steps"][3]["status"] == "MATCH"
    bad = client.post("/api/feedback", json={"decision_id": r["decision_id"], "action": "execute"})
    assert bad.status_code == 409
    ok = client.post("/api/feedback", json={"decision_id": r["decision_id"], "action": "accept"})
    assert ok.json()["state"] == "ACCEPTED"
    assert client.get("/api/decisions/NOPE").status_code == 404


def test_browser_dispatch_matches_http():
    out = json.loads(bridge.dispatch("POST", "/demo/scenarios/2"))
    assert out["status"] == 200 and out["body"]["outcome"] == "NEEDS_REVIEW"


def test_manifest_is_current():
    from scripts.build_manifest import files
    on_disk = json.load(open("web/py_manifest.json"))["files"]
    assert on_disk == files(), "run `make manifest`"
