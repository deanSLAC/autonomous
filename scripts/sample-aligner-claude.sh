#!/usr/bin/env bash
# sample-aligner-claude.sh — headless Claude launcher for the Sample-Holder
# Alignment agent. Drives sample-stage motors (Sx/Sy/Sz/Sr) plus energy,
# emiss, and filter; is barred from upstream optics, KB benders, anchor
# changes, and the spectrometer crystals.
#
# SPEC_PHASE_OVERRIDE=sample_alignment — server-side allowlist permits only
# Sx, Sy, Sz, Sr, energy, emiss, filter; rejects mono/gap/m1*/m2*/slits/Bx/Bz/Tz
# and crystal motors. select_element, get_HERFD_energy, and tracking are
# allowed; align_beamline / xtal_align / set_anchor are NOT.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"
export SPEC_PHASE_OVERRIDE=sample_alignment

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
  --append-system-prompt-file context/Sample-alignment_system-prompt.md \
  --allowedTools "Bash(beamtimehero *)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
