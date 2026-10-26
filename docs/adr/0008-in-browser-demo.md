# ADR 0008: The hosted demo runs the real engine in the browser

**Status:** accepted

## Context
A public demo should not need credentials, a paid API, a server that sleeps on free tiers, or my API key.

## Decision
GitHub Pages serves `web/`. The page loads Pyodide (Python compiled to WebAssembly), loads the `gde` package files listed in `web/py_manifest.json`, and calls `gde.bridge.dispatch()` directly. Locally, `make demo` runs the FastAPI app, and the same UI calls `/api/...`. The core package is standard library only, which is what makes this possible.

## Consequences
- The hosted demo is the real code. It is not a mock-up, and it cannot drift: `tests/test_api.py` checks the routes, and `test_manifest_is_current` checks the file list.
- Nothing leaves the visitor's browser, and a refresh resets everything.
- Cost: about 10 MB on first load (a few seconds). It depends on the Pyodide CDN, so the local demo and static screenshots are the fallbacks (see `docs/DEMO_FALLBACKS.md`).

## Interview questions this decision may trigger
- Why not deploy the API somewhere?
- Is the hosted demo the real code?
- What breaks if the CDN is down?
