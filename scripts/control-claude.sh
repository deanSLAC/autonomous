#!/usr/bin/env bash
# control-claude.sh — unrestricted beamline control agent.
# Phase-unlocked; config in .claude/agents/control.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=unrestricted

launch_agent control
