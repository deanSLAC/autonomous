"""action_log — the durable SPEC-action audit trail.

Writer invariant: every `spec_cmd` action is INSERT'd as an ActionLog
row *before* the command is injected to SPEC. Read-only calls go to
QueryLog. Both tables live in their own sqlite file, independent of
the orchestration DB.
"""

from beamline_tools.action_log.db import (
    finish_action,
    invalidate_for_experiment,
    log_query,
    mark_action_started,
    recent_actions,
    recent_queries,
    start_action,
)
from beamline_tools.action_log.models import ActionLog, QueryLog
from beamline_tools.action_log.session import get_session, init_db

__all__ = [
    "ActionLog",
    "QueryLog",
    "finish_action",
    "get_session",
    "init_db",
    "invalidate_for_experiment",
    "log_query",
    "mark_action_started",
    "recent_actions",
    "recent_queries",
    "start_action",
]
