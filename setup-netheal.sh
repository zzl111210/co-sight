#!/usr/bin/env sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$REPO_ROOT"

PYTHON_BIN=${PYTHON_BIN:-python3}
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'

if [ ! -x .venv/bin/python ]; then
  printf '%s\n' '[1/5] Creating Python virtual environment...'
  "$PYTHON_BIN" -m venv .venv
fi

printf '%s\n' '[2/5] Installing pinned dependencies...'
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  printf '%s\n' '[3/5] Creating local .env from the safe template...'
  cp .env_template .env
else
  printf '%s\n' '[3/5] Existing .env preserved.'
fi

printf '%s\n' '[4/5] Running NetHeal automated tests...'
.venv/bin/python -m unittest discover -s tests -p 'test_netheal*.py' -v

printf '%s\n' '[5/5] Running six acceptance cases...'
.venv/bin/python -m app.netheal.acceptance_runner

printf '%s\n' 'Setup complete. Edit .env locally, then start with:'
printf '%s\n' '  .venv/bin/python cosight_server/deep_research/main.py'
printf '%s\n' 'Open: http://localhost:7788/cosight/netheal.html'
