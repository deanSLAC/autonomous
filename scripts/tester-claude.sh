#!/usr/bin/env bash
# tester-claude.sh — interactive beamline testing agent.
# Phase-unlocked; config in .claude/agents/tester.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=unrestricted

exec claude --agent tester \
  --append-system-prompt-file "$PROJECT_ROOT/.claude/prompts/base-layer.md" \
  --settings .claude/settings.json
