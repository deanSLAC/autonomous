#!/usr/bin/env bash
# Launch the Autonomous Beamline Agent.
#
# Brings up:
#   1. Python venv + dependencies
#   2. SQLite tables
#   3. .opencode/tools/*.ts (regenerated from the Python tool registry)
#   4. opencode server on 127.0.0.1:4096 (no auth — loopback only)
#   5. FastAPI application on :5005

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

echo "[start] initializing DB…"
python server/db/init_db.py

echo "[start] regenerating opencode tool wrappers…"
python scripts/generate_opencode_tools.py

# opencode lives at a fixed loopback address — we set it up, we know
# where it is. OPENCODE_BIN is the only escape hatch (different dev
# machines may install it in different places).
OPENCODE_BIN="${OPENCODE_BIN:-$HOME/.opencode/bin/opencode}"
START_OPENCODE="${START_OPENCODE:-1}"
OPENCODE_PID=""

if [[ "$START_OPENCODE" == "1" ]]; then
    if [[ -z "${SLAC_API_KEY:-}" ]]; then
        echo "[start] WARN: SLAC_API_KEY not set — starting FastAPI only (agent disabled)."
    elif [[ ! -x "$OPENCODE_BIN" ]]; then
        echo "[start] WARN: opencode binary not found at $OPENCODE_BIN. Install via:"
        echo "          curl -fsSL https://opencode.ai/install | bash"
        echo "        Continuing without agent."
    else
        echo "[start] launching opencode on 127.0.0.1:4096"
        "$OPENCODE_BIN" serve --hostname 127.0.0.1 --port 4096 &
        OPENCODE_PID=$!
        trap 'echo "[start] stopping opencode ($OPENCODE_PID)"; kill "$OPENCODE_PID" 2>/dev/null || true' EXIT
        sleep 2
    fi
fi

echo "[start] launching FastAPI on :5005"
exec python server/app.py
