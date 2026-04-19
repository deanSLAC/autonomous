"""Staff-guidance and intervention-resolution queue.

Guidance text that arrives via Slack / Web is stored in the
StaffGuidance table. The orchestrator drains pending guidance at every
outer-loop iteration and injects it into the LLM's next turn as a
"[STEERING]"-tagged system message. Because this is a queue, guidance
submitted while the LLM is mid-tool-call is still delivered on the next
turn — no race conditions.

Interventions (pause-for-human) use asyncio.Event objects keyed by
intervention id so the agent tool that requested the pause resumes as
soon as staff confirms (via Slack button or UI).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from db.autonomy_client import (
    add_guidance,
    consume_pending_guidance,
    create_intervention,
    get_intervention,
    resolve_intervention,
)

logger = logging.getLogger(__name__)


@dataclass
class InterventionWaiter:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: dict = field(default_factory=dict)


class StaffCoordinator:
    """Event/queue coordinator shared by Slack, UI, and orchestrator."""

    def __init__(self):
        self._waiters: Dict[str, InterventionWaiter] = {}
        self._lock = asyncio.Lock()

    # ---- Guidance -----------------------------------------------------

    def record_guidance(
        self,
        *,
        experiment_id: Optional[str],
        source: str,
        author: str,
        text: str,
    ) -> None:
        add_guidance(experiment_id, source, author, text)
        logger.info("staff guidance recorded [%s/%s]: %s", source, author, text[:80])

    def drain_guidance(self, experiment_id: Optional[str]) -> list[dict]:
        return consume_pending_guidance(experiment_id)

    # ---- Interventions ------------------------------------------------

    async def request_intervention(
        self,
        *,
        experiment_id: Optional[str],
        kind: str,
        detail: str,
        timeout_s: float,
        notify: "callable",  # called with (intervention_id, detail)
    ) -> dict:
        """Create an intervention, notify staff, block until resolution."""
        row = create_intervention(experiment_id, kind, detail)
        waiter = InterventionWaiter()
        async with self._lock:
            self._waiters[row.id] = waiter

        try:
            await notify(row.id, detail)
        except Exception as e:
            logger.error("intervention notify failed: %s", e)

        try:
            await asyncio.wait_for(waiter.event.wait(), timeout=timeout_s)
            return waiter.outcome
        except asyncio.TimeoutError:
            resolve_intervention(row.id, status="timed_out", resolver="system",
                                 note=f"no response within {timeout_s}s")
            return {"id": row.id, "status": "timed_out", "resolver": "system"}
        finally:
            async with self._lock:
                self._waiters.pop(row.id, None)

    async def resolve(
        self,
        intervention_id: str,
        *,
        status: str,
        resolver: str,
        note: Optional[str] = None,
    ) -> bool:
        row = get_intervention(intervention_id)
        if row is None:
            return False
        resolve_intervention(intervention_id, status=status, resolver=resolver, note=note)

        async with self._lock:
            waiter = self._waiters.get(intervention_id)
        if waiter is not None:
            waiter.outcome = {
                "id": intervention_id,
                "status": status,
                "resolver": resolver,
                "note": note,
            }
            waiter.event.set()
        return True

    # ---- Simple approval requester for phase transitions --------------

    async def request_approval(self, kind: str, detail: str, timeout_s: float,
                               experiment_id: Optional[str] = None,
                               notify=None) -> dict:
        if notify is None:
            # Without a notify callback, default deny after timeout.
            notify = lambda i, d: _noop_notify(i, d)
        result = await self.request_intervention(
            experiment_id=experiment_id, kind=kind, detail=detail,
            timeout_s=timeout_s, notify=notify,
        )
        # Normalize for callers expecting {"status": "approved"|"denied"|"timeout"}.
        status = result.get("status", "timed_out")
        out_status = {
            "resolved": "approved",
            "denied": "denied",
            "timed_out": "timeout",
        }.get(status, status)
        return {**result, "status": out_status}


async def _noop_notify(intervention_id: str, detail: str) -> None:
    logger.info("[no notify] intervention %s detail=%s", intervention_id, detail)


# Module-level singleton
coordinator = StaffCoordinator()
