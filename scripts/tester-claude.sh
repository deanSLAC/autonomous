#!/usr/bin/env bash
# tester-claude.sh — interactive beamline testing agent.
# Scope unrestricted (top-level `beamtimehero` tree); config in .claude/agents/tester.md.
source "$(dirname "$0")/_agent-common.sh"

exec claude --agent tester \
  --append-system-prompt-file "$PROJECT_ROOT/.claude/prompts/base-layer.md" \
  --settings .claude/settings.json
