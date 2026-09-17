#!/bin/sh
# Start from source without downloading runtime dependencies.
cd "$(dirname "$0")" || exit 1
PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m ai_baby "$@"
