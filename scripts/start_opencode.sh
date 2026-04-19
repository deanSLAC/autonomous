#!/usr/bin/env bash
# Start the local opencode server bound to the SLAC AI Gateway.
#
# Requires:
#   - opencode installed (curl -fsSL https://opencode.ai/install | bash)
#   - SLAC_API_KEY set in env (or .env)
#
# The server must be started from the project root so it sees opencode.json.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a
    source .env
    set +a
fi

if [[ -z "${SLAC_API_KEY:-}" ]]; then
    echo "ERROR: SLAC_API_KEY is not set. Copy .env.example to .env and fill it in." >&2
    exit 2
fi

# Regenerate tool wrappers so the tool surface is always in sync with Python.
python scripts/generate_opencode_tools.py

OPENCODE_BIN="${OPENCODE_BIN:-$HOME/.opencode/bin/opencode}"
if [[ ! -x "$OPENCODE_BIN" ]]; then
    echo "ERROR: opencode binary not found at $OPENCODE_BIN" >&2
    echo "Install with: curl -fsSL https://opencode.ai/install | bash" >&2
    exit 2
fi

HOST="${OPENCODE_HOST:-127.0.0.1}"
PORT="${OPENCODE_PORT:-4096}"

echo "[opencode] starting server on ${HOST}:${PORT} (model=${OPENCODE_MODEL:-slac/us.anthropic.claude-opus-4-6-v1})"
exec "$OPENCODE_BIN" serve --hostname "$HOST" --port "$PORT"
