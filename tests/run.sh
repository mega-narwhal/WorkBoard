#!/usr/bin/env bash
# Canonical runner for the WorkBoard unit suite. Auto-detects a usable pytest:
#   1. python3 -m pytest        (if pytest is installed for a 3.10+ python)
#   2. uv run ... pytest        (ephemeral, fetches python 3.12 + pytest)
# Exits non-zero on any failure, so it's safe to wire into a git pre-push hook.
#
# Targets use `X | None` annotations evaluated at def time → Python 3.10+ only.
set -euo pipefail
cd "$(dirname "$0")/.."

py_ok() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; }

for PY in python3.12 python3.11 python3 python; do
  if py_ok "$PY" && "$PY" -c 'import pytest' 2>/dev/null; then
    echo "→ pytest via $PY"
    exec "$PY" -m pytest "$@"
  fi
done

if command -v uv >/dev/null 2>&1; then
  echo "→ pytest via uv (ephemeral python 3.12)"
  exec uv run --no-project --with pytest --python 3.12 pytest "$@"
fi

echo "error: no python ≥3.10 with pytest, and uv is not installed." >&2
echo "       install pytest (pip install pytest) or uv (https://docs.astral.sh/uv/)." >&2
exit 1
