#!/usr/bin/env bash
# planner-claude.sh — headless Claude launcher for the Planner agent.
# The planner does NOT drive SPEC; it manages the experiment plan
# (sample queue, per-sample reps/count_time, beamtime budget) and
# supervises the data-collection agent's progress.
#
# Tool scoping:
#   * No spec-read / spec-write — calls to those CLIs are rejected
#     at the Bash allowlist level by listing only the allowed trees.
#   * SPEC_PHASE_OVERRIDE intentionally NOT exported. The planner
#     never issues SPEC commands, so a phase is not meaningful; if
#     the planner ever tries one, it'll fail the phase gate as well
#     as the bash allowlist.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"

if [ -n "${BEAMTIMEHERO_CLAUDE_SESSION_ID:-}" ]; then
  SESSION_FLAG=(--resume "$BEAMTIMEHERO_CLAUDE_SESSION_ID")
else
  SESSION_FLAG=(--session-id "$(uuidgen)")
fi

# The planner only needs db / tool / ref / steering subtrees.
# spec-read and spec-write are deliberately NOT allowed.
exec claude -p \
  --output-format stream-json \
  --input-format stream-json \
  --include-partial-messages \
  --verbose \
  --permission-mode acceptEdits \
  --append-system-prompt-file context/Planner_system-prompt.md \
  --allowedTools \
    "Bash(beamtimehero db *)" \
    "Bash(beamtimehero tool *)" \
    "Bash(beamtimehero ref *)" \
    "Bash(beamtimehero steering *)" \
  --disallowedTools "Edit,Write,Agent,Bash(beamtimehero spec-read *),Bash(beamtimehero spec-write *)" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
