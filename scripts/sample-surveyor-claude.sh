#!/usr/bin/env bash
# sample-surveyor-claude.sh — pre-collection sample survey agent.
# Scope enforced by the `surveyor` argparse branch in scripts/beamtimehero.
# Config in .claude/agents/sample-surveyor.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent sample-surveyor
