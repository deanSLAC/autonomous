#!/usr/bin/env bash
# Launch the Autonomous Beamline Agent.
#
#   1. Python venv + dependencies
#   2. beamtimehero_cli pinned-commit check (beamtimehero_cli.pin)
#   3. SQLite tables
#   4. Symlink scripts/beamtimehero → venv/bin/beamtimehero so claude code
#      can invoke the unified CLI as a plain command.
#   5. Verify the `claude` binary is on PATH.
#   6. FastAPI on :5005. claude -p is spawned as a subprocess per turn —
#      no persistent harness server. LLM_GATEWAY={slac,stanford,default}
#      picks the upstream claude code talks to.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [[ ! -d venv ]]; then
    echo "[start] creating venv…"
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo "[start] installing requirements…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# The toolbelt is an editable install of a sibling checkout, so what is
# checked out there is what we run. Refuse to launch on an unverified
# commit — see beamtimehero_cli.pin for the bump procedure and the
# BEAMTIMEHERO_CLI_REF escape hatch.
echo "[start] checking beamtimehero_cli pin…"
python scripts/check_cli_pin.py

echo "[start] initializing DB…"
python -c "from orchestration.plan_store.init_db import init_db; init_db()"

# Symlink scripts/beamtimehero into venv/bin so the claude-code agent (and
# anyone else with the venv activated) can invoke it as a plain command.
# Idempotent.
if [[ -x scripts/beamtimehero ]]; then
    ln -sf "$(pwd)/scripts/beamtimehero" "venv/bin/beamtimehero"
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "[start] ERROR: 'claude' binary not on PATH. Install claude code first." >&2
    exit 2
fi
echo "[start] claude binary: $(command -v claude)"
echo "[start] launching FastAPI on :5005 (claude -p subprocess per turn — no harness server)"
exec python main.py
