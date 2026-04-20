#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi
[ -f .env ] || cp .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
