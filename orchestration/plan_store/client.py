"""CRUD helpers for the autonomy-specific tables.

Keeps the original `db.client` untouched — this module just adds CRUD
for PhaseTransitionLog, ExperimentPlan, StaffGuidance, and
InterventionRequest.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlmodel import select

from orchestration.plan_store.models import (
    AgentRun,
    ExperimentPlan,
    InterventionRequest,
    PhaseTransitionLog,
    PlanEdit,
    StaffGuidance,
)
from orchestration.plan_store.session import _commit_with_retry, get_session


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

def record_phase_transition(
    experiment_id: str,
    previous_phase: str,
    new_phase: str,
    justification: str,
    allowed: bool,
    preconditions: list[dict] | None = None,
    human_approved: bool | None = None,
    reason: str | None = None,
) -> PhaseTransitionLog:
    row = PhaseTransitionLog(
        experiment_id=experiment_id,
        previous_phase=previous_phase,
        new_phase=new_phase,
        justification=justification,
        allowed=allowed,
        preconditions_json=json.dumps(preconditions or []),
        human_approved=human_approved,
        reason=reason,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def list_phase_transitions(experiment_id: str) -> list[dict]:
    with get_session() as session:
        stmt = (
            select(PhaseTransitionLog)
            .where(PhaseTransitionLog.experiment_id == experiment_id)
            .order_by(PhaseTransitionLog.timestamp.desc())
        )
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "previous_phase": r.previous_phase,
                "new_phase": r.new_phase,
                "justification": r.justification,
                "allowed": r.allowed,
                "human_approved": r.human_approved,
                "reason": r.reason,
                "preconditions": json.loads(r.preconditions_json or "[]"),
            }
            for r in session.exec(stmt)
        ]


# ---------------------------------------------------------------------------
# Experiment plan
# ---------------------------------------------------------------------------

class StaleVersionError(Exception):
    """Raised when upsert_experiment_plan detects a concurrent update."""


def upsert_experiment_plan(
    experiment_id: str,
    *,
    beamtime_total_hours: float | None = None,
    phase: str | None = None,
    plan: dict | None = None,
    beamtime_elapsed_hours: float | None = None,
    notes: str | None = None,
    expected_version: int | None = None,
) -> ExperimentPlan:
    with get_session() as session:
        row = session.exec(
            select(ExperimentPlan).where(ExperimentPlan.experiment_id == experiment_id)
        ).first()
        if row is None:
            row = ExperimentPlan(experiment_id=experiment_id)
            session.add(row)
        elif expected_version is not None and row.version != expected_version:
            raise StaleVersionError(
                f"plan version mismatch for {experiment_id}: "
                f"expected {expected_version}, found {row.version}"
            )
        if beamtime_total_hours is not None:
            row.beamtime_total_hours = beamtime_total_hours
        if beamtime_elapsed_hours is not None:
            row.beamtime_elapsed_hours = beamtime_elapsed_hours
        if phase is not None:
            row.phase = phase
        if plan is not None:
            row.plan_json = json.dumps(plan)
        if notes is not None:
            row.notes = notes
        row.updated_at = datetime.now()
        row.version = (row.version or 0) + 1
        session.add(row)
        _commit_with_retry(session)
        session.refresh(row)
    return row


def get_plan(experiment_id: str) -> Optional[dict]:
    with get_session() as session:
        row = session.exec(
            select(ExperimentPlan).where(ExperimentPlan.experiment_id == experiment_id)
        ).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "experiment_id": row.experiment_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "beamtime_total_hours": row.beamtime_total_hours,
            "beamtime_elapsed_hours": row.beamtime_elapsed_hours,
            "phase": row.phase,
            "plan": json.loads(row.plan_json or "{}"),
            "notes": row.notes,
            "version": getattr(row, "version", 0) or 0,
        }


# ---------------------------------------------------------------------------
# Staff guidance
# ---------------------------------------------------------------------------

def add_guidance(
    experiment_id: str | None,
    source: str,
    author: str,
    text: str,
) -> StaffGuidance:
    row = StaffGuidance(
        experiment_id=experiment_id,
        source=source,
        author=author,
        text=text,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def consume_pending_guidance(experiment_id: str) -> list[dict]:
    """Mark all pending guidance consumed and return it as plain dicts.

    Returns dicts (not ORM rows) so the result is usable after the session
    has closed.
    """
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.consumed == False)  # noqa: E712
            .where(StaffGuidance.experiment_id == experiment_id)
        )
        stmt = stmt.order_by(StaffGuidance.timestamp)
        rows: list[StaffGuidance] = list(session.exec(stmt))
        now = datetime.now()
        snapshot: list[dict] = []
        for r in rows:
            snapshot.append({
                "id": r.id,
                "source": r.source,
                "author": r.author,
                "text": r.text,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            })
            r.consumed = True
            r.consumed_at = now
            session.add(r)
        session.commit()
        return snapshot


def list_guidance(experiment_id: str, limit: int = 50) -> list[dict]:
    """Return deliberate human-directed guidance only.

    Plan-edit side effects previously wrote rows here with
    source='web-plan'; those show up in the Plan History panel, not
    here, so they are filtered out. Legacy rows in the DB are filtered
    at read time — no migration needed.
    """
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.source != "web-plan")
            .where(StaffGuidance.experiment_id == experiment_id)
        )
        stmt = stmt.order_by(StaffGuidance.timestamp.desc()).limit(limit)
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "source": r.source,
                "author": r.author,
                "text": r.text,
                "consumed": r.consumed,
            }
            for r in session.exec(stmt)
        ]


# ---------------------------------------------------------------------------
# Intervention requests (pause-for-human)
# ---------------------------------------------------------------------------

def create_intervention(
    experiment_id: str | None,
    kind: str,
    detail: str,
    slack_channel: str | None = None,
    slack_ts: str | None = None,
) -> InterventionRequest:
    row = InterventionRequest(
        experiment_id=experiment_id,
        kind=kind,
        detail=detail,
        slack_channel=slack_channel,
        slack_ts=slack_ts,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def resolve_intervention(
    intervention_id: str,
    *,
    status: str,
    resolver: str,
    note: str | None = None,
) -> Optional[InterventionRequest]:
    with get_session() as session:
        row = session.get(InterventionRequest, intervention_id)
        if row is None:
            return None
        row.status = status
        row.resolver = resolver
        row.resolver_note = note
        row.resolved_at = datetime.now()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def reset_run_state(experiment_id: str) -> dict:
    """Operator-triggered hard reset: mark prior action-log rows as
    invalidated, resolve any still-pending interventions with
    status='reset', and put the plan back in `setup` phase.

    Experiment config, sample holders, and sample queue are untouched
    — the operator explicitly resets the *run*, not the experiment.
    Returns a small summary for the UI.
    """
    # ActionLog lives in the beamline_tools DB — invalidate via that package.
    from beamtimehero_cli.action_log.db import invalidate_for_experiment

    invalidated_actions = invalidate_for_experiment(experiment_id)

    now = datetime.now()
    with get_session() as session:
        pending = list(session.exec(
            select(InterventionRequest).where(
                InterventionRequest.experiment_id == experiment_id,
                InterventionRequest.status == "waiting",
            )
        ))
        for iv in pending:
            iv.status = "reset"
            iv.resolver = "operator"
            iv.resolver_note = "run reset from dashboard"
            iv.resolved_at = now
            session.add(iv)

        plan_row = session.exec(
            select(ExperimentPlan).where(
                ExperimentPlan.experiment_id == experiment_id
            )
        ).first()
        if plan_row is not None:
            plan_row.phase = "setup"
            session.add(plan_row)

        session.commit()

    return {
        "invalidated_actions": invalidated_actions,
        "resolved_interventions": len(pending),
    }


def list_open_interventions(experiment_id: str | None = None) -> list[dict]:
    with get_session() as session:
        stmt = select(InterventionRequest).where(InterventionRequest.status == "waiting")
        if experiment_id:
            stmt = stmt.where(InterventionRequest.experiment_id == experiment_id)
        stmt = stmt.order_by(InterventionRequest.created_at)
        return [_intervention_to_dict(r) for r in session.exec(stmt)]


def get_intervention(intervention_id: str) -> Optional[dict]:
    with get_session() as session:
        row = session.get(InterventionRequest, intervention_id)
        if row is None:
            return None
        return _intervention_to_dict(row)


# ---------------------------------------------------------------------------
# Plan edit log
# ---------------------------------------------------------------------------

def log_plan_edit(
    experiment_id: str,
    *,
    author: str,
    action: str,
    target_id: str | None = None,
    payload: dict | None = None,
    reason: str | None = None,
) -> PlanEdit:
    row = PlanEdit(
        experiment_id=experiment_id,
        author=author,
        action=action,
        target_id=target_id,
        payload_json=json.dumps(payload or {}, default=str),
        reason=reason,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def list_plan_edits(experiment_id: str, limit: int = 100) -> list[dict]:
    with get_session() as session:
        stmt = (
            select(PlanEdit)
            .where(PlanEdit.experiment_id == experiment_id)
            .order_by(PlanEdit.timestamp.desc())
            .limit(limit)
        )
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "author": r.author,
                "action": r.action,
                "target_id": r.target_id,
                "payload": json.loads(r.payload_json or "{}"),
                "reason": r.reason,
            }
            for r in session.exec(stmt)
        ]


def _intervention_to_dict(r: InterventionRequest) -> dict:
    return {
        "id": r.id,
        "experiment_id": r.experiment_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "kind": r.kind,
        "detail": r.detail,
        "status": r.status,
        "resolver": r.resolver,
        "resolver_note": r.resolver_note,
        "slack_channel": r.slack_channel,
        "slack_ts": r.slack_ts,
    }


# ---------------------------------------------------------------------------
# Steering (StaffGuidance state-machine columns)
# ---------------------------------------------------------------------------
#
# These helpers operate on the lifecycle columns added to StaffGuidance:
# orchestrator_ack_at, ack_comment, active_agent_run_id, active_agent_ack_at,
# completed_at, result, slack_channel, slack_thread_ts, is_stop.
#
# See the `StaffGuidance` docstring in models.py for the full lifecycle.
# The CLI surface lives at `beamtimehero steering ...`.

class SteeringRow(BaseModel):
    """The steering-row contract shared by the orchestrator tick, the
    `beamtimehero steering` CLI, and the dashboard.

    `orchestrator_tick` key-reads `is_stop` / `target_agent_type` to
    decide which agents to kill or spawn — when this was a hand-typed
    19-key dict literal, a renamed key made STOP rows silently inert
    (`.get()` → None → falsy). The model is now the single source of
    the field names; serialize with `model_dump(mode="json")`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    source: str
    author: str
    text: str
    consumed: bool = False                  # legacy
    consumed_at: Optional[datetime] = None  # legacy
    orchestrator_ack_at: Optional[datetime] = None
    ack_comment: Optional[str] = None
    active_agent_run_id: Optional[str] = None
    active_agent_ack_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    slack_channel: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    is_stop: bool = False
    slack_replied_at: Optional[datetime] = None
    target_agent_type: Optional[str] = None


def _steering_to_dict(r: StaffGuidance) -> dict:
    return SteeringRow.model_validate(r).model_dump(mode="json")


def add_steering(
    experiment_id: str | None,
    source: str,
    author: str,
    text: str,
    *,
    slack_channel: str | None = None,
    slack_thread_ts: str | None = None,
    is_stop: bool = False,
) -> dict:
    """Insert a steering row with full Slack provenance + STOP flag.

    Superset of `add_guidance`. Returns the inserted row as a dict so the
    caller can use the ID after the session closes.
    """
    row = StaffGuidance(
        experiment_id=experiment_id,
        source=source,
        author=author,
        text=text,
        slack_channel=slack_channel,
        slack_thread_ts=slack_thread_ts,
        is_stop=is_stop,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


def list_pending_steering(
    experiment_id: str,
    *,
    limit: int = 50,
) -> list[dict]:
    """Return steering rows where `completed_at IS NULL`, most-recent first."""
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.completed_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
        )
        stmt = stmt.order_by(StaffGuidance.timestamp.desc()).limit(limit)  # type: ignore[union-attr]
        return [_steering_to_dict(r) for r in session.exec(stmt)]


def list_unacked_steering(
    experiment_id: str,
    *,
    limit: int = 50,
) -> list[dict]:
    """Return pending rows the active agent has NOT yet acked, most-recent first."""
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.completed_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.active_agent_ack_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
        )
        stmt = stmt.order_by(StaffGuidance.timestamp.desc()).limit(limit)  # type: ignore[union-attr]
        return [_steering_to_dict(r) for r in session.exec(stmt)]


def ack_steering(
    steering_id: str,
    *,
    agent_run_id: str | None = None,
) -> Optional[dict]:
    """Set `active_agent_ack_at=now`; if `agent_run_id` set, link it too."""
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.active_agent_ack_at = datetime.now()
        if agent_run_id is not None:
            row.active_agent_run_id = agent_run_id
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


def set_steering_comment(
    steering_id: str,
    comment: str,
) -> Optional[dict]:
    """Set `ack_comment` on a steering row."""
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.ack_comment = comment
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


def complete_steering(
    steering_id: str,
    *,
    result: str,
) -> Optional[dict]:
    """Mark a steering row complete: set `result` and `completed_at=now`."""
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.result = result
        row.completed_at = datetime.now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


def defer_steering(
    steering_id: str,
    *,
    reason: str,
    target_agent_type: str | None = None,
) -> Optional[dict]:
    """Defer a steering row: write `ack_comment="deferred — <reason>"`
    and (optionally) record which agent_type the orchestrator should
    re-dispatch to.

    Does NOT set `completed_at`. The orchestrator's tick scans for
    deferred rows whose `active_agent_run_id` has finished and respawns
    `target_agent_type` (with a focused-task seed) to handle them.
    """
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.ack_comment = f"deferred — {reason}"
        if target_agent_type:
            row.target_agent_type = target_agent_type
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


def record_orchestrator_ack(
    steering_id: str,
    *,
    comment: str,
    active_agent_run_id: str | None = None,
) -> Optional[dict]:
    """Record the orchestrator's ack on a steering row.

    Used by the orchestrator state machine. Sets `orchestrator_ack_at=now`,
    `ack_comment`, and optionally links the agent that will handle it.
    """
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.orchestrator_ack_at = datetime.now()
        row.ack_comment = comment
        if active_agent_run_id is not None:
            row.active_agent_run_id = active_agent_run_id
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)


# ---------------------------------------------------------------------------
# Steering-state-machine helpers used by the orchestrator loop
# ---------------------------------------------------------------------------

def list_new_steering_for_orchestrator(
    experiment_id: str,
) -> list[dict]:
    """Rows the orchestrator has not yet ack'd, oldest first (FIFO).

    Excludes rows already completed (e.g. STOP rows that the fast-path
    completed without setting `orchestrator_ack_at`) so they don't get
    re-dispatched as normal steering.
    """
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.orchestrator_ack_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.completed_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
        )
        stmt = stmt.order_by(StaffGuidance.timestamp)  # type: ignore[union-attr]
        return [_steering_to_dict(r) for r in session.exec(stmt)]


def list_completed_unposted_steering(experiment_id: str) -> list[dict]:
    """Completed rows whose Slack reply hasn't been posted yet.

    Filters: `completed_at IS NOT NULL AND slack_replied_at IS NULL
    AND slack_thread_ts IS NOT NULL`. Ordered by `completed_at` ascending so
    older completions reply first.
    """
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.completed_at.is_not(None))  # type: ignore[union-attr]
            .where(StaffGuidance.slack_replied_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.slack_thread_ts.is_not(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
            .order_by(StaffGuidance.completed_at)  # type: ignore[union-attr]
        )
        return [_steering_to_dict(r) for r in session.exec(stmt)]


def list_orphaned_deferred_steering(experiment_id: str) -> list[dict]:
    """Steering rows that were deferred to an agent which has since finished.

    Predicate: `orchestrator_ack_at IS NOT NULL AND completed_at IS NULL
    AND active_agent_run_id IS NOT NULL` AND the linked AgentRun has
    `completed_at IS NOT NULL`. The orchestrator picks these up to spawn a
    fresh agent for the still-pending row.
    """
    with get_session() as session:
        stmt = (
            select(StaffGuidance, AgentRun)
            .join(
                AgentRun,
                AgentRun.id == StaffGuidance.active_agent_run_id,
            )
            .where(StaffGuidance.orchestrator_ack_at.is_not(None))  # type: ignore[union-attr]
            .where(StaffGuidance.completed_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.active_agent_run_id.is_not(None))  # type: ignore[union-attr]
            .where(AgentRun.completed_at.is_not(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
            .order_by(StaffGuidance.timestamp)  # type: ignore[union-attr]
        )
        return [_steering_to_dict(r) for (r, _agent) in session.exec(stmt)]


def list_pending_stops(experiment_id: str) -> list[dict]:
    """STOP rows that haven't been completed yet — orchestrator runs ASAP."""
    with get_session() as session:
        stmt = (
            select(StaffGuidance)
            .where(StaffGuidance.is_stop == True)  # noqa: E712
            .where(StaffGuidance.completed_at.is_(None))  # type: ignore[union-attr]
            .where(StaffGuidance.experiment_id == experiment_id)
            .order_by(StaffGuidance.timestamp)  # type: ignore[union-attr]
        )
        return [_steering_to_dict(r) for r in session.exec(stmt)]


def mark_steering_replied(steering_id: str) -> Optional[dict]:
    """Stamp `slack_replied_at=now` so we don't double-post on later ticks."""
    with get_session() as session:
        row = session.get(StaffGuidance, steering_id)
        if row is None:
            return None
        row.slack_replied_at = datetime.now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _steering_to_dict(row)
