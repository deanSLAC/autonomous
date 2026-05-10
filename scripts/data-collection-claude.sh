#!/usr/bin/env bash
# data-collection-claude.sh — headless Claude launcher for the Data
# Collection agent. Drives sample-stage moves between spots, energy
# scans, and emission scans for the currently mounted holder; bounded
# by the planner-managed per-sample reps / count_time budget.
#
# SPEC_PHASE_OVERRIDE=collection — server-side allowlist permits Sx, Sy,
# Sz, Sr, energy, emiss, filter, plus collection macros (run_xas,
# emiss_scan, run_collection, select_element, get_HERFD_energy, tracking).
# Upstream optics, KB benders, anchor changes, and spectrometer crystals
# are all rejected.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"
export SPEC_PHASE_OVERRIDE=collection

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
  --append-system-prompt-file context/Sample-collection_system-prompt.md \
  --allowedTools "Bash(beamtimehero *)" "Bash(date)" "Skill(assess-sample-damage)" "Skill(analyze-statistical-convergence)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
