#!/bin/bash
set -euo pipefail
# Touch variant only; identical EDID on a non-touch sample did NOT establish compatibility.
# Caller must review its guide and supply --confirm-profile. EDID checks remain active.
exec screen-config apply "$@" --profile 6.2inch-420x960-60hz-ltm-zl480
