#!/usr/bin/env bash
# Shared setup for all agent launcher scripts. Source this, don't execute.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

export PATH="$PROJECT_ROOT/scripts:$PATH"

if [ -n "${BEAMTIMEHERO_CLAUDE_SESSION_ID:-}" ]; then
  SESSION_FLAG=(--resume "$BEAMTIMEHERO_CLAUDE_SESSION_ID")
else
  SESSION_FLAG=(--session-id "$(uuidgen)")
fi

# launch_agent <agent-name> [extra-claude-flags...]
launch_agent() {
  local agent_name="$1"; shift
  exec claude --agent "$agent_name" -p \
    --append-system-prompt-file "$PROJECT_ROOT/.claude/prompts/base-layer.md" \
    --output-format stream-json \
    --input-format stream-json \
    --include-partial-messages \
    --verbose \
    "$@" \
    "${SESSION_FLAG[@]}"
}
