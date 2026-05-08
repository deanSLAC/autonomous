#!/usr/bin/env bash
# Stub for the per-phase Beamline Alignment Claude agent.
# The real script is on master and wraps `claude -p` with the
# beamline-alignment system prompt + tool allowlist. Kept as a stub
# here so the dashboard's spawn/kill plumbing has something to launch.
set -euo pipefail
echo "[bl-aligner-claude] stub: pretending to run beamline alignment ($$)"
trap 'echo "[bl-aligner-claude] received SIGTERM, exiting"; exit 0' TERM
sleep 60
echo "[bl-aligner-claude] stub done"
