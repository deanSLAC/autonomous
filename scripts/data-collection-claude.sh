#!/usr/bin/env bash
# Stub for the per-phase Data Collection Claude agent.
set -euo pipefail
echo "[data-collection-claude] stub: pretending to run data collection ($$)"
trap 'echo "[data-collection-claude] received SIGTERM, exiting"; exit 0' TERM
sleep 60
echo "[data-collection-claude] stub done"
