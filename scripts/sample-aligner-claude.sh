#!/usr/bin/env bash
# Stub for the per-phase Sample Alignment Claude agent.
set -euo pipefail
echo "[sample-aligner-claude] stub: pretending to run sample alignment ($$)"
trap 'echo "[sample-aligner-claude] received SIGTERM, exiting"; exit 0' TERM
sleep 60
echo "[sample-aligner-claude] stub done"
