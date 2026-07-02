#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  CODEX_PY="/Users/donnaile/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  if [[ -x "$CODEX_PY" ]]; then
    PYTHON_BIN="$CODEX_PY"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info < (3, 14) else 1)
PY
then
  echo "Python 3.14+ cannot install this app's pinned test dependencies. Set PYTHON to Python 3.12 or 3.13." >&2
  exit 1
fi

"$PYTHON_BIN" -m venv .venv-test
source .venv-test/bin/activate

python -m pip install -q -r requirements.txt

PYTHONPATH=. python -m compileall -q app
PYTHONPATH=. python -m unittest discover -s tests
