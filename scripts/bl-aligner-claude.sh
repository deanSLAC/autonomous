#!/usr/bin/env bash
# bl-aligner-claude.sh — beamline alignment agent (upstream optics).
# Phase-locked to beamline_alignment; config in .claude/agents/bl-aligner.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=beamline_alignment

launch_agent bl-aligner
