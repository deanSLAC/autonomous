#!/usr/bin/env bash
# bl-aligner-claude.sh — beamline alignment agent (upstream optics).
# Scope enforced by the `blaligner` argparse branch in scripts/beamtimehero.
# Config in .claude/agents/bl-aligner.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent bl-aligner
