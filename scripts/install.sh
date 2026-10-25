#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$SOURCE_DIR/src"
exec /usr/bin/python3 -m pi_setting.installer --source "$SOURCE_DIR" "$@"
