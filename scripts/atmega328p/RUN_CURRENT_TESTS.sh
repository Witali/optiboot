#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
"${PYTHON:-python3}" "$BASE/run_tests.py" --build "$@"
