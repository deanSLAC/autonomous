"""ActionLog + QueryLog tables — the tools-layer audit trail.

Lives in its own SQLite file (`data/beamline_tools.db`) so the tools
layer is independent of the orchestration layer's schema. The
`experiment_id` / `phase_run_id` columns are soft references (indexed
strings, no FK constraint) because the experiment + phase_run tables
live in the orchestration DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def generate_id() -> str:
    return uuid.uuid4().hex[:12]


class ActionLog(SQLModel, table=True):
    """Durable record of every spec_cmd action call.

    Writer invariant: the row is INSERT'd before the command is injected to
    the SPEC screen session. Even if SPEC hangs, the row still exists.
    """
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, index=True)
    phase_run_id: Optional[str] = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    phase: str = Field(index=True)
    command: str = Field(index=True)
    args_json: str = "[]"
    spec_string_sent: str = ""
    justification: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_json: Optional[str] = None
    screen_output: Optional[str] = None
    scan_number: Optional[int] = None
    success: Optional[int] = None  # 1 ok, 0 err, None in progress
    error_message: Optional[str] = None
    agent: str = Field(default="llm")
    # Set by orchestration.api.reset_run so prior runs are invisible to
    # re-run guards and the action-log UI without losing audit data.
    invalidated_at: Optional[datetime] = None


class QueryLog(SQLModel, table=True):
    """Non-mutating spec_cmd read calls — separate log so action_log stays clean."""
    id: str = Field(default_factory=generate_id, primary_key=True)
    experiment_id: Optional[str] = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=datetime.now, index=True)
    phase: str = Field(default="unknown")
    command: str = Field(index=True)
    args_json: str = "[]"
    result_json: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None
