"""Verify every optional dependency can be imported in the active venv.

Run from the project root:

    python scripts/check_deps.py

Prints one line per dep with OK / FAIL and the exact error if it fails.
Exit code 0 only when every dep imports cleanly.
"""
from __future__ import annotations

import importlib
import sys

# (display name, import name)
DEPS = [
    ("fastapi",       "fastapi"),
    ("uvicorn",       "uvicorn"),
    ("yfinance",      "yfinance"),
    ("curl_cffi",     "curl_cffi"),
    ("pandas",        "pandas"),
    ("numpy",         "numpy"),
    ("scipy",         "scipy"),
    ("scikit-learn",  "sklearn"),
    ("arch",          "arch"),
    ("hmmlearn",      "hmmlearn"),
    ("pywavelets",    "pywt"),
    ("umap-learn",    "umap"),
    ("ripser",        "ripser"),
    ("persim",        "persim"),
    ("kmapper",       "kmapper"),
    ("vaderSentiment","vaderSentiment"),
    ("plotly",        "plotly"),
    ("reportlab",     "reportlab"),
]


def main() -> int:
    print(f"Python     : {sys.version.split()[0]}")
    print(f"Executable : {sys.executable}\n")
    failures: list[tuple[str, str]] = []
    for name, mod in DEPS:
        try:
            m = importlib.import_module(mod)
            version = getattr(m, "__version__", "?")
            print(f"  [OK  ] {name:<16}  (import {mod})  v{version}")
        except Exception as exc:
            failures.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"  [FAIL] {name:<16}  (import {mod})  -> {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"{len(failures)} dep(s) failed to import.")
        print("Try:  pip install -r requirements.txt   (make sure the correct venv is active)")
        return 1
    print("All dependencies imported successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
