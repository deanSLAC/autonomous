"""Leaf functions for `beamtimehero steering ...`.

Each function takes a parsed argparse Namespace and returns the integer
exit code, after printing a JSON envelope on stdout. Shape mirrors the
rest of beamtimehero:

  * success:    {"ok": true, ...row}            → exit 0
  * not found:  {"ok": false, "error": "..."}   → exit 1
  * list cmd:   JSON array of row dicts         → exit 0

The orchestrator state machine spawns control agents with
`BEAMTIMEHERO_AGENT_RUN_ID=<id>` in the environment so any `ack` issued
by that agent automatically links its agent_run id without the agent
having to know it.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from orchestration.plan_store.client import (
    ack_steering,
    complete_steering,
    defer_steering,
    list_pending_steering,
    list_unacked_steering,
    set_steering_comment,
)


_RUN_ID_ENV = "BEAMTIMEHERO_AGENT_RUN_ID"


def _resolve_agent_run_id(args: argparse.Namespace) -> str | None:
    """Prefer an explicit --agent-run-id flag; fall back to env var."""
    flag = getattr(args, "agent_run_id", None)
    if flag:
        return flag
    env = os.environ.get(_RUN_ID_ENV)
    return env or None


def _print_ok(row: dict[str, Any]) -> int:
    payload = {"ok": True, **row}
    print(json.dumps(payload, default=str))
    return 0


def _print_not_found(steering_id: str) -> int:
    print(json.dumps({
        "ok": False,
        "error": f"steering ID {steering_id} not found",
    }))
    return 1


# ---------------------------------------------------------------------------
# Leaf handlers
# ---------------------------------------------------------------------------

def cmd_pending(args: argparse.Namespace) -> int:
    experiment_id = getattr(args, "experiment_id", None)
    if getattr(args, "unacked", False):
        rows = list_unacked_steering(experiment_id=experiment_id)
    else:
        rows = list_pending_steering(experiment_id=experiment_id)
    print(json.dumps(rows, default=str))
    return 0


def cmd_ack(args: argparse.Namespace) -> int:
    agent_run_id = _resolve_agent_run_id(args)
    row = ack_steering(args.id, agent_run_id=agent_run_id)
    if row is None:
        return _print_not_found(args.id)
    return _print_ok(row)


def cmd_set_comment(args: argparse.Namespace) -> int:
    row = set_steering_comment(args.id, args.text)
    if row is None:
        return _print_not_found(args.id)
    return _print_ok(row)


def cmd_complete(args: argparse.Namespace) -> int:
    row = complete_steering(args.id, result=args.result)
    if row is None:
        return _print_not_found(args.id)
    return _print_ok(row)


def cmd_defer(args: argparse.Namespace) -> int:
    row = defer_steering(args.id, reason=args.reason)
    if row is None:
        return _print_not_found(args.id)
    return _print_ok(row)
