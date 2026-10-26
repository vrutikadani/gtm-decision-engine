PY ?= python3

.PHONY: demo test eval manifest check

demo:            ## API + demo UI on http://localhost:8000
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m gde.server

test:
	$(PY) -m pytest -q

eval:
	$(PY) evals/run_eval.py

manifest:        ## list of Python files the in-browser demo loads
	$(PY) scripts/build_manifest.py

check: test eval
