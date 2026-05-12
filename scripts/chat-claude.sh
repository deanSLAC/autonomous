#!/usr/bin/env bash
# chat-claude.sh — chat agent (Slack + UI chat box).
# Restricted tooling (no SPEC mutation); config in .claude/agents/chat.md.
CHAT_CWD="$(pwd)"
source "$(dirname "$0")/_agent-common.sh"

export BEAMTIMEHERO_CHAT_AGENT=1

cd "$CHAT_CWD"
launch_agent chat
