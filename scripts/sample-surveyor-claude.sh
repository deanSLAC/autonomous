#!/usr/bin/env bash
# sample-surveyor-claude.sh — headless Claude launcher for the Sample
# Surveyor agent. Runs a pre-collection survey of every sample on the
# mounted holder: tunes filter count to a 50 kcps working point, takes
# the first beam-damage check (two scans on a spot, optionally more
# after fresh-spot moves), and uploads per-sample
# {filter_count, counts_per_sec, survey_energy} back to the DB. The
# planner agent spawns next, consuming those survey numbers to size
# per-sample n_scans.
#
# SPEC_PHASE_OVERRIDE=collection — there is no dedicated `survey` phase
# in the allowlist. The survey is a precursor activity within the same
# physical scope as data collection (run_xas, select_element, sample
# stage moves, filter/emiss/energy control), so the `collection` phase
# is the correct gate. Server-side allowlist permits Sx, Sy, Sz, Sr,
# energy, emiss, filter, plus collection macros (run_xas, emiss_scan,
# run_collection, select_element, get_HERFD_energy, tracking).
# Upstream optics, KB benders, anchor changes, and spectrometer
# crystals are all rejected.
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
  --append-system-prompt-file context/Sample-surveyor_system-prompt.md \
  --allowedTools "Bash(beamtimehero *)" "Skill(assess-sample-damage)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
