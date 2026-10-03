#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../backend"

uv_bin="${UV_BIN:-}"
if [ -z "$uv_bin" ]; then
  uv_bin="$(command -v uv 2>/dev/null || true)"
fi
for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  if [ -z "$uv_bin" ] && [ -x "$candidate" ]; then
    uv_bin="$candidate"
  fi
done

if [ -z "$uv_bin" ]; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

export UV_NO_PROGRESS=1
export UV_LINK_MODE=copy

"$uv_bin" sync --locked --no-editable

exec "$uv_bin" run --locked --no-sync uvicorn software_developer_agent.main:app \
  --app-dir src \
  --reload \
  --host 127.0.0.1 \
  --port 8000
