#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../backend"

if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "Backend environment is missing. Run:" >&2
  echo "  cd backend && python3.11 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
  exit 1
fi

exec .venv/bin/uvicorn software_developer_agent.main:app \
  --app-dir src \
  --reload \
  --host 127.0.0.1 \
  --port 8000
