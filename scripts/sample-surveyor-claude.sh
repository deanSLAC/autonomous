#!/usr/bin/env bash
# sample-surveyor-claude.sh — pre-collection sample survey agent.
# Phase-locked to collection; config in .claude/agents/sample-surveyor.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=collection

launch_agent sample-surveyor
