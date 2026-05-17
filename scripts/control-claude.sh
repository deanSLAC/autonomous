#!/usr/bin/env bash
# control-claude.sh — unrestricted beamline control agent.
# Uses the top-level `beamtimehero` tree (no role filter); config in .claude/agents/control.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent control
