"""Phase-transition logic for the autonomous orchestrator.

`transition_phase(target, justification)` is the single mechanism for
changing the current phase. Forward transitions require preconditions to
be met. Backward transitions go through Slack for human approval with a
default-deny timeout.

This module is deliberately framework-agnostic: Slack + WebSocket hooks
are injected via callbacks so smoke tests can drive it with stubs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from db.autonomy_client import (
    record_phase_transition,
    upsert_experiment_plan,
    create_intervention,
    resolve_intervention,
)
from spec import phase_allowlist, spec_cmd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------

@dataclass
class Precondition:
    name: str
    ok: bool
    detail: str


class PreconditionChecker:
    """Lightweight wrapper over in-memory facts tracked by the orchestrator.

    The orchestrator calls `.record(fact, value)` as tools succeed (e.g.
    `align_beamline_ok=True`), and the checker consults those facts plus
    the DB plan to decide if a transition is permitted.
    """

    def __init__(self):
        self._facts: dict[str, object] = {}

    def record(self, fact: str, value: object) -> None:
        self._facts[fact] = value

    def get(self, fact: str, default=None):
        return self._facts.get(fact, default)


def seed_from_action_log(checker: "PreconditionChecker", experiment_id: str) -> None:
    """Populate phase-completion facts from the persisted action_log.

    Tool calls run in opencode-spawned *subprocesses* of FastAPI, so any
    fact recorded on the parent-process checker after align_beamline or
    calibrate_mono completes is invisible to the next tool call that
    tries to advance the phase. Without this, `align_beamline_ok` never
    flips and the agent re-runs the whole (minutes-long) alignment.

    The action_log *is* shared (sqlite on disk), so we re-derive the
    facts here from commands known to have succeeded. Idempotent; safe
    to call before every precondition check.
    """
    try:
        from action_log.db import recent_actions
    except Exception:
        return
    try:
        actions = recent_actions(limit=200, experiment_id=experiment_id)
    except Exception:
        return

    # bl_align → {xes_align, sample_align}
    if any(a.get("command") == "align_beamline" and a.get("success") == 1 for a in actions):
        checker.record("align_beamline_ok", True)
    for a in actions:  # recent first
        if a.get("command") == "calibrate_mono" and a.get("success") == 1:
            result = a.get("result") or {}
            residual = None
            if isinstance(result, dict):
                raw = result.get("residual_ev")
                if raw is None and "raw" in result and isinstance(result["raw"], str):
                    import re as _re
                    m = _re.search(r"residual[_ ]ev[=:\s]*([-+]?\d*\.?\d+)", result["raw"])
                    if m:
                        raw = m.group(1)
                if raw is not None:
                    try:
                        residual = float(raw)
                    except (TypeError, ValueError):
                        residual = 0.0
            # A successful calibrate_mono implies the residual was
            # under threshold. Fall back to 0.0 if we can't parse one.
            checker.record("calibrate_mono_residual_ev", 0.0 if residual is None else residual)
            break

    # xes_align → sample_align
    if any(a.get("command") == "align_xes_spectrometer" and a.get("success") == 1
           for a in actions):
        checker.record("align_xes_ok", True)
    if any(a.get("command") in ("set_xes_en_offset", "xes_en_offset") and a.get("success") == 1
           for a in actions):
        checker.record("xes_en_offset_set", True)

    def check(self, prev: str, target: str) -> list[Precondition]:
        P = phase_allowlist
        checks: list[Precondition] = []

        def add(name: str, ok: bool, detail: str):
            checks.append(Precondition(name=name, ok=ok, detail=detail))

        # setup → beamline_alignment
        if prev == P.PHASE_SETUP and target == P.PHASE_BL_ALIGN:
            add("experiment_loaded", bool(self.get("experiment_id")),
                "an experiment must be selected (configure it on the /config page)")
            add("beam_present", bool(self.get("beam_good", True)),
                "SPEAR beam good & gap owned (mock ok)")

        # beamline_alignment → xes_alignment | sample_alignment
        if prev == P.PHASE_BL_ALIGN and target in (P.PHASE_XES_ALIGN, P.PHASE_SAMPLE_ALIGN):
            add("align_beamline_ok", bool(self.get("align_beamline_ok", False)),
                "align_beamline must have succeeded in this session")
            residual = float(self.get("calibrate_mono_residual_ev", 0.0) or 0.0)
            add("calibrate_mono_residual_under_0.2_ev",
                abs(residual) < 0.2,
                f"calibrate_mono residual is {residual:.3f} eV (must be < 0.2 eV)")

        # xes_alignment → sample_alignment
        if prev == P.PHASE_XES_ALIGN and target == P.PHASE_SAMPLE_ALIGN:
            add("align_xes_ok", bool(self.get("align_xes_ok", False)),
                "align_xes_spectrometer must have succeeded")
            add("xes_en_offset_set",
                self.get("xes_en_offset_set", False) is not False,
                "XES_EN_OFFSET must have been set")

        # sample_alignment → collection
        if prev == P.PHASE_SAMPLE_ALIGN and target == P.PHASE_COLLECTION:
            expected = int(self.get("n_samples_configured", 0) or 0)
            aligned = int(self.get("n_samples_aligned", 0) or 0)
            add("all_samples_aligned",
                expected > 0 and aligned >= expected,
                f"{aligned}/{expected} configured samples have stored positions")

        # collection → complete
        if prev == P.PHASE_COLLECTION and target == P.PHASE_COMPLETE:
            done = self.get("collection_complete", False)
            budget = self.get("beamtime_remaining_hours", 1.0)
            add("collection_done_or_budget_exhausted",
                bool(done) or (budget is not None and budget <= 0),
                "all samples reached targets, or beamtime exhausted",
            )

        return checks


# ---------------------------------------------------------------------------
# Approval callback types
# ---------------------------------------------------------------------------

ApprovalRequester = Callable[[str, str], Awaitable[dict]]
"""async (kind, detail) → {'status': 'approved'|'denied', 'resolver': str}.

Blocks until staff resolves the request — there is no timeout."""


# ---------------------------------------------------------------------------
# The transition function
# ---------------------------------------------------------------------------

@dataclass
class TransitionResult:
    allowed: bool
    previous_phase: str
    current_phase: str
    preconditions: list[dict]
    human_approval_required: bool
    reason: Optional[str] = None
    intervention_id: Optional[str] = None


async def transition_phase(
    experiment_id: str,
    target_phase: str,
    justification: str,
    checker: PreconditionChecker,
    approval_requester: Optional[ApprovalRequester] = None,
) -> TransitionResult:
    prev = spec_cmd.get_phase()
    if target_phase not in phase_allowlist.ALL_PHASES:
        return _deny(experiment_id, prev, target_phase, justification,
                     f"unknown phase: {target_phase}", [])

    if prev == target_phase:
        return _deny(experiment_id, prev, target_phase, justification,
                     "already in target phase", [])

    direction = phase_allowlist.direction(prev, target_phase)

    # Forward: check preconditions
    if direction == "forward":
        checks = checker.check(prev, target_phase)
        failures = [c for c in checks if not c.ok]
        if failures:
            reason = "; ".join(f"{c.name}: {c.detail}" for c in failures)
            record_phase_transition(
                experiment_id, prev, target_phase, justification,
                allowed=False,
                preconditions=[_c_to_dict(c) for c in checks],
                reason=reason,
            )
            return TransitionResult(
                allowed=False, previous_phase=prev, current_phase=prev,
                preconditions=[_c_to_dict(c) for c in checks],
                human_approval_required=False, reason=reason,
            )
        _commit(experiment_id, prev, target_phase, justification, checks, human_approved=None)
        return TransitionResult(
            allowed=True, previous_phase=prev, current_phase=target_phase,
            preconditions=[_c_to_dict(c) for c in checks],
            human_approval_required=False,
        )

    # Backward: must go through Slack approval. We wait indefinitely —
    # if rolling back a phase requires a human, the agent waits for one.
    kind = "backward_transition"
    detail = (
        f"Agent requesting backward phase transition: {prev} → {target_phase}. "
        f"Reason: {justification}. "
        f"Reply 'approve' to allow, or 'deny' to keep current phase."
    )

    intervention = create_intervention(
        experiment_id=experiment_id, kind=kind, detail=detail,
    )

    if approval_requester is None:
        # No Slack wired — default deny.
        resolve_intervention(intervention.id, status="denied", resolver="system",
                             note="no approval requester wired — default deny")
        record_phase_transition(
            experiment_id, prev, target_phase, justification,
            allowed=False,
            preconditions=[], human_approved=False,
            reason="backward transition denied (no approval channel)",
        )
        return TransitionResult(
            allowed=False, previous_phase=prev, current_phase=prev,
            preconditions=[], human_approval_required=True,
            reason="backward transition denied (no approval channel)",
            intervention_id=intervention.id,
        )

    try:
        resp = await approval_requester(kind, detail)
    except Exception as e:
        resolve_intervention(intervention.id, status="denied", resolver="system",
                             note=f"approval channel error: {e}")
        return TransitionResult(
            allowed=False, previous_phase=prev, current_phase=prev,
            preconditions=[], human_approval_required=True,
            reason=f"approval channel error: {e}", intervention_id=intervention.id,
        )

    status = resp.get("status", "timeout")
    resolver = resp.get("resolver", "unknown")
    if status == "approved":
        resolve_intervention(intervention.id, status="resolved", resolver=resolver)
        _commit(experiment_id, prev, target_phase, justification, [], human_approved=True)
        return TransitionResult(
            allowed=True, previous_phase=prev, current_phase=target_phase,
            preconditions=[], human_approval_required=True,
            intervention_id=intervention.id,
        )
    resolve_intervention(intervention.id, status=status, resolver=resolver)
    record_phase_transition(
        experiment_id, prev, target_phase, justification,
        allowed=False,
        preconditions=[], human_approved=False,
        reason=f"backward transition {status}",
    )
    return TransitionResult(
        allowed=False, previous_phase=prev, current_phase=prev,
        preconditions=[], human_approval_required=True,
        reason=f"backward transition {status}",
        intervention_id=intervention.id,
    )


def _commit(experiment_id, prev, target, justification, checks, human_approved):
    record_phase_transition(
        experiment_id, prev, target, justification,
        allowed=True,
        preconditions=[_c_to_dict(c) for c in checks],
        human_approved=human_approved,
    )
    spec_cmd.set_phase(target, experiment_id=experiment_id)
    upsert_experiment_plan(experiment_id, phase=target)


def _deny(experiment_id, prev, target, justification, reason, checks) -> TransitionResult:
    record_phase_transition(
        experiment_id, prev, target, justification,
        allowed=False, preconditions=[_c_to_dict(c) for c in checks], reason=reason,
    )
    return TransitionResult(
        allowed=False, previous_phase=prev, current_phase=prev,
        preconditions=[_c_to_dict(c) for c in checks],
        human_approval_required=False, reason=reason,
    )


def _c_to_dict(c: Precondition) -> dict:
    return {"name": c.name, "ok": c.ok, "detail": c.detail}
