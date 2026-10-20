#!/usr/bin/env bash
# Start ClipForge (uses the project's virtualenv)
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

PORT="${PORT:-7860}"
echo "ClipForge running at http://localhost:$PORT"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
