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

from orchestration.plan_store.client import (
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
        notify: "callable",  # called with (intervention_id, detail)
        timeout_s: Optional[float] = None,
    ) -> dict:
        """Create an intervention, notify staff, block until resolution.

        With `timeout_s=None` (the default) this waits indefinitely.
        Pass a positive number only if you have a real reason for the
        agent to give up on its own (smoke tests do this).
        """
        row = create_intervention(experiment_id, kind, detail)
        waiter = InterventionWaiter()
        async with self._lock:
            self._waiters[row.id] = waiter

        try:
            await notify(row.id, detail)
        except Exception as e:
            logger.error("intervention notify failed: %s", e)

        # Two wake-up paths:
        #  1) In-process resolve (fast): coordinator.resolve() sets the
        #     Event directly. Used when the resolver and the waiter live
        #     in the same process.
        #  2) Cross-process resolve (polled): opencode spawns tool calls
        #     in a *subprocess*, so its in-memory _waiters dict is
        #     separate from the FastAPI parent's. The parent still
        #     updates the DB row, and we poll the row here so the
        #     subprocess wakes up too. 2s cadence is human-scale
        #     (nobody notices a 2s lag on a physical action), and cheap.
        async def _watch_db() -> dict:
            while True:
                await asyncio.sleep(2.0)
                cur = get_intervention(row.id)
                if cur is None:
                    continue
                status = cur.get("status")
                if status and status != "pending":
                    return {
                        "id": row.id,
                        "status": status,
                        "resolver": cur.get("resolver") or "unknown",
                        "note": cur.get("note"),
                    }

        try:
            event_task = asyncio.create_task(waiter.event.wait())
            db_task = asyncio.create_task(_watch_db())
            tasks = {event_task, db_task}
            try:
                if timeout_s is None:
                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED,
                    )
                else:
                    done, _ = await asyncio.wait(
                        tasks, timeout=timeout_s,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        resolve_intervention(row.id, status="timed_out",
                                             resolver="system",
                                             note=f"no response within {timeout_s}s")
                        return {"id": row.id, "status": "timed_out",
                                "resolver": "system"}
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()

            if event_task in done:
                return waiter.outcome
            return db_task.result()
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

    async def request_approval(self, kind: str, detail: str,
                               experiment_id: Optional[str] = None,
                               notify=None) -> dict:
        """Block until staff approves or denies. No timeout."""
        if notify is None:
            notify = _noop_notify
        result = await self.request_intervention(
            experiment_id=experiment_id, kind=kind, detail=detail,
            notify=notify,
        )
        # Normalize for callers expecting {"status": "approved"|"denied"}.
        status = result.get("status", "denied")
        out_status = {"resolved": "approved", "denied": "denied"}.get(status, status)
        return {**result, "status": out_status}


async def _noop_notify(intervention_id: str, detail: str) -> None:
    logger.info("[no notify] intervention %s detail=%s", intervention_id, detail)


# Module-level singleton
coordinator = StaffCoordinator()
