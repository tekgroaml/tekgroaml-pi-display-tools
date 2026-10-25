#!/bin/bash
set -euo pipefail
# Requires an installed pi-setting 2.3+ application. EDID checks remain active.
exec screen-config apply "$@" --profile 4.0inch-720x720-60hz-wks-lontium-semi
