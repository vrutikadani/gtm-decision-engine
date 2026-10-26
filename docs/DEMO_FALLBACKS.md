# If the demo will not load in an interview

Four layers, in order. Have the first two open in tabs before the call starts.

1. **Hosted demo:** https://vrutikadani.github.io/gtm-decision-engine/. It needs the Pyodide CDN (cdn.jsdelivr.net) on first load, about 10 MB. After the page loads, everything runs in the tab with no network.
2. **Local demo:** `make demo`, then open http://localhost:8000. No internet needed once dependencies are installed. Run `pip install -r requirements.txt` the day before. You get the same scenarios plus `/docs`.
3. **Static assets:** `docs/assets/`:
   - `shot-*.png` for each screen
   - `demo.mp4` / `demo.gif` (84 seconds)
   - `a-system.png` to `d-champion-resolution.png`
4. **README walkthrough:** the README tells the whole story without running anything. Then open `docs/FAILURE_POSTMORTEM.md`.

## Pre-interview checklist
- [ ] Hosted demo loaded once in this browser (warms the cache)
- [ ] `make demo` running locally, scenario 1 clicked
- [ ] `docs/assets/demo.mp4` downloaded
- [ ] Editor open on `gde/decisions/engine.py` and `gde/champions/resolution.py`
