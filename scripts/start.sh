#!/usr/bin/env bash
# Launch the Autonomous Beamline Agent.
#
# Brings up:
#   1. Python venv + dependencies
#   2. SQLite tables
#   3. .opencode/tools/*.ts (regenerated from the Python tool registry)
#   4. opencode server (SLAC AI Gateway provider)
#   5. FastAPI application on $PORT (default 8080)

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
        HOST="${OPENCODE_HOST:-127.0.0.1}"
        OC_PORT="${OPENCODE_PORT:-4096}"
        echo "[start] launching opencode on ${HOST}:${OC_PORT}"
        "$OPENCODE_BIN" serve --hostname "$HOST" --port "$OC_PORT" &
        OPENCODE_PID=$!
        trap 'echo "[start] stopping opencode ($OPENCODE_PID)"; kill "$OPENCODE_PID" 2>/dev/null || true' EXIT
        # Give opencode a moment to bind
        sleep 2
    fi
fi

PORT="${PORT:-8080}"
echo "[start] launching FastAPI on :${PORT}"
exec python server/app.py
