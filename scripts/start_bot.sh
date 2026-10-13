#!/usr/bin/env bash
set -euo pipefail
TENDR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TENDR_ROOT/bot"
exec "$TENDR_ROOT/.venv/bin/python" -m bot.main
