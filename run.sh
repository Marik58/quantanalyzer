#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Pick the right activate path for the platform — Git Bash on Windows uses
# .venv/Scripts/activate; Linux/macOS use .venv/bin/activate.
if [ -f .venv/Scripts/activate ]; then
    ACTIVATE=.venv/Scripts/activate
else
    ACTIVATE=.venv/bin/activate
fi

if [ ! -d .venv ]; then
    python -m venv .venv 2>/dev/null || python3 -m venv .venv
    if [ -f .venv/Scripts/activate ]; then
        ACTIVATE=.venv/Scripts/activate
    else
        ACTIVATE=.venv/bin/activate
    fi
    source "$ACTIVATE"
    pip install -r requirements.txt
else
    source "$ACTIVATE"
fi

[ -f .env ] || cp .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
