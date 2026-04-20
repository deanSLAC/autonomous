#!/usr/bin/env bash
# Launch the Autonomous Beamline Agent.
#
# Brings up:
#   1. Python venv + dependencies
#   2. SQLite tables
#   3. .opencode/tools/*.ts (regenerated from the Python tool registry)
#   4. opencode server on 127.0.0.1:4096 (no auth — loopback only)
#   5. FastAPI application on :5005
#
# FastAPI only initializes the orchestrator at startup if opencode's
# HTTP endpoint is reachable, so we actively poll opencode before
# launching FastAPI rather than sleeping a fixed amount.

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

OPENCODE_HOST="${OPENCODE_HOST:-127.0.0.1}"
OPENCODE_PORT="${OPENCODE_PORT:-4096}"
OPENCODE_BIN="${OPENCODE_BIN:-$HOME/.opencode/bin/opencode}"
START_OPENCODE="${START_OPENCODE:-1}"
OPENCODE_PID=""

wait_for_opencode() {
    local host="$1" port="$2" tries="${3:-60}"
    local i=0
    while (( i < tries )); do
        if curl -fsS --max-time 1 "http://${host}:${port}/session" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
        ((i++))
    done
    return 1
}

cleanup() {
    if [[ -n "$OPENCODE_PID" ]] && kill -0 "$OPENCODE_PID" 2>/dev/null; then
        echo "[start] stopping opencode ($OPENCODE_PID)"
        kill "$OPENCODE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [[ "$START_OPENCODE" == "1" ]]; then
    if [[ -z "${SLAC_API_KEY:-}" ]]; then
        echo "[start] ERROR: SLAC_API_KEY not set. Copy .env.example to .env and fill it in." >&2
        exit 2
    elif [[ ! -x "$OPENCODE_BIN" ]]; then
        echo "[start] ERROR: opencode binary not found at $OPENCODE_BIN" >&2
        echo "        Install: curl -fsSL https://opencode.ai/install | bash" >&2
        exit 2
    fi

    # If something is already listening on 4096, assume the user has a
    # long-running opencode and reuse it rather than double-starting.
    if curl -fsS --max-time 1 "http://${OPENCODE_HOST}:${OPENCODE_PORT}/session" >/dev/null 2>&1; then
        echo "[start] opencode already running on ${OPENCODE_HOST}:${OPENCODE_PORT} — reusing"
    else
        echo "[start] launching opencode on ${OPENCODE_HOST}:${OPENCODE_PORT}"
        "$OPENCODE_BIN" serve --hostname "$OPENCODE_HOST" --port "$OPENCODE_PORT" &
        OPENCODE_PID=$!
        echo "[start] waiting for opencode to accept connections…"
        if ! wait_for_opencode "$OPENCODE_HOST" "$OPENCODE_PORT" 60; then
            echo "[start] ERROR: opencode did not become ready within 30s. Aborting." >&2
            exit 1
        fi
        echo "[start] opencode ready."
    fi
fi

echo "[start] launching FastAPI on :5005"
exec python server/app.py
