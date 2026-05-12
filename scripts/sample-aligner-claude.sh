#!/usr/bin/env bash
# sample-aligner-claude.sh — sample holder alignment agent.
# Phase-locked to sample_alignment; config in .claude/agents/sample-aligner.md.
source "$(dirname "$0")/_agent-common.sh"

export SPEC_PHASE_OVERRIDE=sample_alignment

launch_agent sample-aligner
