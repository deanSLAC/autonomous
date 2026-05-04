#!/usr/bin/env bash
# Launch the Autonomous Beamline Agent.
#
# AGENT_BACKEND=claude_code (default):
#   1. Python venv + dependencies
#   2. SQLite tables
#   3. Symlink scripts/beamtimehero → venv/bin/beamtimehero so claude code
#      can invoke the unified CLI as a plain command.
#   4. Verify the `claude` binary is on PATH.
#   5. FastAPI on :5005. claude -p is spawned as a subprocess per turn —
#      no persistent harness server. LLM_GATEWAY={slac,stanford,default}
#      picks the upstream claude code talks to.
#
# AGENT_BACKEND=opencode:
#   1+2+3. Same.
#   4. Regenerate .opencode/tools/*.ts from the Python tool registry.
#   5. Start opencode server on 127.0.0.1:4096 (no auth — loopback only)
#      and FastAPI on :5005. FastAPI only initializes the orchestrator
#      at startup if opencode's HTTP endpoint is reachable, so we
#      actively poll opencode before launching FastAPI.

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
python -c "from orchestration.plan_store.init_db import init_db; init_db()"

# .env provides AGENT_BACKEND. Anything else is a misconfiguration.
if [[ -z "${AGENT_BACKEND:-}" ]]; then
    echo "[start] ERROR: AGENT_BACKEND not set. Did you cp .env.example .env?" >&2
    exit 2
fi
echo "[start] AGENT_BACKEND=${AGENT_BACKEND}"

# Symlink scripts/beamtimehero into venv/bin so the claude-code agent (and
# anyone else with the venv activated) can invoke it as a plain command.
# Idempotent.
if [[ -x scripts/beamtimehero ]]; then
    ln -sf "$(pwd)/scripts/beamtimehero" "venv/bin/beamtimehero"
fi

if [[ "$AGENT_BACKEND" == "claude_code" ]]; then
    if ! command -v claude >/dev/null 2>&1; then
        echo "[start] ERROR: 'claude' binary not on PATH. Install claude code or set AGENT_BACKEND=opencode." >&2
        exit 2
    fi
    echo "[start] claude binary: $(command -v claude)"
    echo "[start] launching FastAPI on :5005 (claude -p subprocess per turn — no harness server)"
    exec python main.py
fi

# --- opencode path (default) ----------------------------------------------
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
    # opencode reads its own provider config from opencode.json, but it
    # still needs an API key in the environment for the active gateway.
    case "${LLM_GATEWAY:-slac}" in
        slac)
            if [[ -z "${SLAC_API_KEY:-}" ]]; then
                echo "[start] ERROR: SLAC_API_KEY not set (required for LLM_GATEWAY=slac). Check your .env." >&2
                exit 2
            fi ;;
        stanford)
            if [[ -z "${STANFORD_API_KEY:-}" ]]; then
                echo "[start] ERROR: STANFORD_API_KEY not set (required for LLM_GATEWAY=stanford). Check your .env." >&2
                exit 2
            fi ;;
    esac
    if [[ ! -x "$OPENCODE_BIN" ]]; then
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
exec python main.py
