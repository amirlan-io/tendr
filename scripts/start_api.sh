#!/usr/bin/env bash
set -euo pipefail
TENDR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TENDR_ROOT/backend"
exec "$TENDR_ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${TENDR_API_PORT:-8000}"
