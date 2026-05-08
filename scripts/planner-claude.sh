#!/usr/bin/env bash
# Stub for the planner-only Claude agent (not currently surfaced in the
# dashboard tile grid but kept registered in PHASE_SCRIPTS so the
# runner can spawn it from the chat / Slack steering paths).
set -euo pipefail
echo "[planner-claude] stub ($$)"
trap 'echo "[planner-claude] received SIGTERM, exiting"; exit 0' TERM
sleep 60
echo "[planner-claude] stub done"
