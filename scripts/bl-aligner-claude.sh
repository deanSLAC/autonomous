#!/usr/bin/env bash
# bl-aligner-claude.sh — headless Claude launcher for the Beamline-Alignment
# agent. Drives upstream optics (mono, gap, m1/m2, slits, KB benders) and
# the diagnostic tool, but is barred from the spectrometer and from
# arbitrary motor moves outside the beamline_alignment phase allowlist.
#
# Mirrors control-claude.sh in shape; differences:
#   * SPEC_PHASE_OVERRIDE=beamline_alignment (was unrestricted) — server-side
#     allowlist gates motors/macros to mono, gap, m1*, m2*, slits, Bx/Bz,
#     Tz/Tp, Sx/Sy/Sz/Sr (diagnostic moves), filter; rejects spectrometer
#     motors (emiss, Az/Dz, c1y..c7y) and collection-only macros.
#   * --append-system-prompt-file points to BL-aligner_system-prompt.md.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env so SPEC_MOCK / SPEC_TRANSPORT propagate to claude and every
# beamtimehero subprocess it spawns.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"
export SPEC_PHASE_OVERRIDE=beamline_alignment

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
  --append-system-prompt-file context/BL-aligner_system-prompt.md \
  --allowedTools "Bash(beamtimehero *)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh \
  "${SESSION_FLAG[@]}"
