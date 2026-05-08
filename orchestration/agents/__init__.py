"""orchestration.agents — registry + lifecycle for spawned Claude Code agents.

Every Claude subprocess (control / chat / dm) the orchestrator spawns is
tracked in the `agentrun` SQLModel table. This package owns that registry
and the subprocess plumbing — Popen, stream-json drain, killpg, and the
FastAPI startup-sweep / shutdown-sweep helpers.

Public API:
    spawn(...)                  → start an agent, return run_id immediately
    kill(run_id, reason=...)    → SIGTERM then SIGKILL the process group
    list_active(agent_type=...) → registry rows where completed_at IS NULL
    get_run(run_id)             → single row dict
    purge_orphans_at_startup()  → reap rows from a previous server crash
    kill_all_at_shutdown()      → clean teardown for FastAPI lifespan

The `agent_type='control' AND completed_at IS NULL` predicate is the
active-control-agent gate the orchestrator state machine reads — see
`runs.find_active_control()`.
"""

from orchestration.agents.runs import (
    create_run,
    set_pid,
    complete_run,
    get_run,
    list_active,
    find_active_control,
)
from orchestration.agents.spawn import (
    spawn,
    kill,
    purge_orphans_at_startup,
    kill_all_at_shutdown,
)

__all__ = [
    "spawn",
    "kill",
    "list_active",
    "get_run",
    "purge_orphans_at_startup",
    "kill_all_at_shutdown",
    "create_run",
    "set_pid",
    "complete_run",
    "find_active_control",
]
