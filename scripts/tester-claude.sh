#!/usr/bin/env bash
# tester-claude.sh — launch Claude for beamline tool testing
# Phase-unlocked, sandbox to beamtimehero CLI only.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env so SPEC_MOCK / SPEC_TRANSPORT / etc. propagate to claude and
# to every beamtimehero subprocess it spawns. Without this, scripts/beamtimehero's
# early `os.getenv("SPEC_MOCK", "1")` check (line 43) runs *before* config.py's
# load_dotenv() and silently defaults to mock mode.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PATH="$(pwd)/scripts:$PATH"
export SPEC_PHASE_OVERRIDE=unrestricted

exec claude \
  --settings .claude/settings.json \
  --append-system-prompt-file context/beamtimehero_context.md \
  --allowedTools "Bash(beamtimehero *)" \
  --disallowedTools "Edit,Write,Agent" \
  --tools "Bash,Read" \
  --model "opus" \
  --effort xhigh