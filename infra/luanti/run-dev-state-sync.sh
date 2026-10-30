#!/usr/bin/env bash
# Dev state-sync on 127.0.0.1:5212 over the SAME sqlite the dev MUD uses (services/mud/data).
# Needs a venv with fastapi + uvicorn at data/luanti/venv (pip install fastapi uvicorn).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PA_GAMESTATE_SQLITE="$ROOT/services/mud/data/gamestate.dev.sqlite"
exec "$ROOT/data/luanti/venv/bin/uvicorn" app:app --app-dir "$ROOT/services/state-sync" --host 127.0.0.1 --port 5212
