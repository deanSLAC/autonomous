#!/usr/bin/env bash
# sample-aligner-claude.sh — sample holder alignment agent.
# Scope enforced by the `samplealigner` argparse branch in scripts/beamtimehero.
# Config in .claude/agents/sample-aligner.md.
source "$(dirname "$0")/_agent-common.sh"

launch_agent sample-aligner
