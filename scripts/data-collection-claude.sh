#!/usr/bin/env bash
# data-collection-claude.sh — data collection agent.
# Scope enforced by the `collector` argparse branch in scripts/beamtimehero.
# Config in .claude/agents/data-collection.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent data-collection
