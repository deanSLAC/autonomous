#!/usr/bin/env bash
# data-collection-claude.sh — data collection agent.
# Phase-locked to collection; config in .claude/agents/data-collection.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=collection

launch_agent data-collection
