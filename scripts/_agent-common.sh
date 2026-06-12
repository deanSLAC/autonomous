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

# Map the configured LLM gateway (.env LLM_GATEWAY + <GATEWAY>_* vars) onto
# the ANTHROPIC_* env the claude CLI reads. Single source of truth is
# orchestration.config.gateway_config — this just serializes it. Best-effort:
# if the python side fails (e.g. missing .env in a dev checkout), the agent
# falls back to claude's on-disk auth, same as LLM_GATEWAY=default.
if GATEWAY_EXPORTS="$("$PROJECT_ROOT/venv/bin/python" -m orchestration.agent.gateway_env 2>/dev/null)"; then
  eval "$GATEWAY_EXPORTS"
fi

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
