#!/usr/bin/env bash
# planner-claude.sh — planner agent (experiment plan management).
# Phase-unlocked (planner never issues SPEC commands); config in .claude/agents/planner.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent planner
