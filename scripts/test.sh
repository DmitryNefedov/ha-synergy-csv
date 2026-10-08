#!/usr/bin/env bash
# Run a command inside the test image (HA 2026.9.4 / Python 3.14 + pytest harness).
# Default: the whole test suite with coverage.  Examples:
#   scripts/test.sh                      # full suite
#   scripts/test.sh pytest tests/test_parser.py
#   scripts/test.sh ruff check .
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q -f docker/Dockerfile.test -t synergy-csv-test . >/dev/null
if [ $# -eq 0 ]; then
  set -- pytest --cov --cov-report=term-missing
fi
exec docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD":/repo -w /repo synergy-csv-test "$@"
