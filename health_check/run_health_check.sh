#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="${PLATFORM_PYTHON:-python3}"

export PYTHONDONTWRITEBYTECODE=1
umask 077

exec "$PYTHON_BIN" -B "$SCRIPT_DIR/check_research_assets.py" \
  --config "$SCRIPT_DIR/health_check_config.json"
