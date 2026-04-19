"""CRUD helpers for the autonomy-specific tables.

Keeps the original `db.client` untouched — this module just adds CRUD
for PhaseTransitionLog, ExperimentPlan, StaffGuidance, and
InterventionRequest.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlmodel import select

from db.client import get_session
from db.models import (
    ExperimentPlan,
    InterventionRequest,
    PhaseTransitionLog,
    PlanEdit,
    StaffGuidance,
)


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

def upsert_experiment_plan(
    experiment_id: str,
    *,
    beamtime_total_hours: float | None = None,
    phase: str | None = None,
    plan: dict | None = None,
    beamtime_elapsed_hours: float | None = None,
    notes: str | None = None,
) -> ExperimentPlan:
    with get_session() as session:
        row = session.exec(
            select(ExperimentPlan).where(ExperimentPlan.experiment_id == experiment_id)
        ).first()
        if row is None:
            row = ExperimentPlan(experiment_id=experiment_id)
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
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def get_experiment_plan(experiment_id: str) -> Optional[dict]:
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


def consume_pending_guidance(experiment_id: str | None) -> list[dict]:
    """Mark all pending guidance consumed and return it as plain dicts.

    Returns dicts (not ORM rows) so the result is usable after the session
    has closed.
    """
    with get_session() as session:
        stmt = select(StaffGuidance).where(StaffGuidance.consumed == False)  # noqa: E712
        if experiment_id:
            stmt = stmt.where(StaffGuidance.experiment_id == experiment_id)
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


def list_guidance(experiment_id: str | None, limit: int = 50) -> list[dict]:
    with get_session() as session:
        stmt = select(StaffGuidance).order_by(StaffGuidance.timestamp.desc()).limit(limit)
        if experiment_id:
            stmt = (
                select(StaffGuidance)
                .where(StaffGuidance.experiment_id == experiment_id)
                .order_by(StaffGuidance.timestamp.desc())
                .limit(limit)
            )
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
