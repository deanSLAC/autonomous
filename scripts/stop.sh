#!/usr/bin/env bash
# Stop the Autonomous Beamline Agent — kills FastAPI (:5005).
# Idempotent: silently succeeds if nothing is up.

set -u
cd "$(dirname "$0")/.."

FASTAPI_PORT="${FASTAPI_PORT:-5005}"

kill_port() {
    local port="$1" label="$2"
    local pids
    pids="$(lsof -ti :"$port" 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then
        echo "[stop] $label (:$port) not running"
        return 0
    fi
    echo "[stop] stopping $label (:$port) — pids: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    # Give it a beat, then SIGKILL anything that didn't exit.
    sleep 1
    local remaining
    remaining="$(lsof -ti :"$port" 2>/dev/null || true)"
    if [[ -n "$remaining" ]]; then
        echo "[stop] force-killing $label — pids: $remaining"
        # shellcheck disable=SC2086
        kill -9 $remaining 2>/dev/null || true
    fi
}

kill_port "$FASTAPI_PORT" "FastAPI"

echo "[stop] done."
