"""orchestration.agents — registry + lifecycle for spawned Claude Code agents.

Every Claude subprocess (phase agents + chat) the orchestrator spawns is
tracked in the `agentrun` SQLModel table. This package owns that
registry and the subprocess plumbing — Popen, stream-json drain (chat
path only), killpg, and the FastAPI startup-sweep / shutdown-sweep
helpers.

Public API:
    spawn(...)                  → start a chat-class agent, return run_id
    kill(run_id, reason=...)    → SIGTERM then SIGKILL the process group
    list_active(agent_type=...) → registry rows where completed_at IS NULL
    get_run(run_id)             → single row dict
    purge_orphans_at_startup()  → reap rows from a previous server crash
    kill_all_at_shutdown()      → clean teardown for FastAPI lifespan

Phase agents (agent_type matches phase slug) are spawned via
`orchestration.agent.phase_runner.start(slug)`, which uses these CRUD
helpers to register the row before Popen.
"""

from orchestration.agents.runs import (
    create_run,
    set_pid,
    complete_run,
    get_run,
    list_active,
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
]
