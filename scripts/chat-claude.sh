#!/usr/bin/env bash
# chat-claude.sh — headless Claude launcher for chat agents.
#
# Chat agents serve the Slack chat channel, bot DMs, and the UI chat box.
# Distinct from control-claude.sh in three ways:
#   * RESTRICTED tooling — only db / ref / tool subtrees of beamtimehero,
#     plus Read. NO spec-read, NO spec-write, no SPEC mutation at all.
#   * NO SPEC_PHASE_OVERRIDE=unrestricted — chat agents must never bypass
#     the phase gate.
#   * BEAMTIMEHERO_CHAT_AGENT=1 is set so any future code path can detect
#     "we're running inside a chat agent".
#
# Resume semantics match control-claude.sh: if the orchestrator passes
# BEAMTIMEHERO_CLAUDE_SESSION_ID we --resume it, else we mint a fresh
# session id with uuidgen so the spawn helper can capture it from the
# stream-json output for future resumes.
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
export BEAMTIMEHERO_CHAT_AGENT=1

# Resume an existing claude session if the chat router handed us one;
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
  --allowedTools "Bash(beamtimehero db *)" "Bash(beamtimehero ref *)" "Bash(beamtimehero tool *)" "Read" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
