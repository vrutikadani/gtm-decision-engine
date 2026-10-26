"""Writes web/py_manifest.json: the engine files the hosted demo loads into Pyodide.
api.py and server.py are excluded (FastAPI is not needed in the browser)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"gde/api.py", "gde/server.py"}


def files():
    out = []
    for p in sorted((ROOT / "gde").rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and p.suffix in {".py", ".json"} and rel not in SKIP and "__pycache__" not in rel:
            out.append(rel)
    return out


if __name__ == "__main__":
    (ROOT / "web" / "py_manifest.json").write_text(json.dumps({"files": files()}, indent=1) + "\n")
    print(f"{len(files())} files")
