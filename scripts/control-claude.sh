#!/usr/bin/env bash
# control-claude.sh — headless Claude launcher for orchestrator-spawned
# control agents that drive the beamline.
#
# Differs from tester-claude.sh:
#   * non-interactive: uses `claude -p` with stream-json on stdin/stdout
#     so the spawn helper can feed a seed prompt and read the result.
#   * resumes via $BEAMTIMEHERO_CLAUDE_SESSION_ID when set, else generates
#     a fresh session id with uuidgen so the spawn helper can capture it.
#   * SPEC_PHASE_OVERRIDE=unrestricted gives the agent full beamline access.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env so SPEC_MOCK / SPEC_TRANSPORT / etc. propagate to claude and
# to every beamtimehero subprocess it spawns.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"
export SPEC_PHASE_OVERRIDE=unrestricted

# Resume an existing claude session if the orchestrator handed us one;
# otherwise mint a new id so the spawn helper can capture it from
# stream-json output for future --resume.
if [ -n "${BEAMTIMEHERO_CLAUDE_SESSION_ID:-}" ]; then
  SESSION_FLAG=(--resume "$BEAMTIMEHERO_CLAUDE_SESSION_ID")
else
  SESSION_FLAG=(--session-id "$(uuidgen)")
fi

exec claude -p \
  --output-format stream-json \
  --input-format stream-json \
  --include-partial-messages \
  --verbose \
  --permission-mode acceptEdits \
  --append-system-prompt-file context/beamtimehero_context.md \
  --allowedTools "Bash(beamtimehero *)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
