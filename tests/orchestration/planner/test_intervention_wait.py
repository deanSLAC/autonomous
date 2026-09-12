"""The cross-process intervention watcher must actually wait for staff.

`request_human_intervention` is supposed to block until a human resolves
the row. Rows are created with status `"waiting"` (see
`plan_store/models.py` InterventionRequest.status), so the DB poll inside
`StaffCoordinator.request_intervention` must treat `"waiting"` — not
`"pending"` — as "still blocked". Comparing against `"pending"` made the
very first poll look like a resolution and the agent sailed on without
the human ever touching the row.

Two cases, one per direction:
  * the row stays `waiting`      -> the watcher never returns
  * the row flips to `resolved`  -> the watcher returns that outcome
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.planner import staff_guidance  # noqa: E402


class _Row:
    """Stand-in for the InterventionRequest returned by create_intervention."""

    def __init__(self, row_id: str = "intv-1"):
        self.id = row_id


def _db_row(status: str, **over) -> dict:
    """A row shaped like client._intervention_to_dict()."""
    row = {
        "id": "intv-1",
        "experiment_id": "exp-1",
        "created_at": "2026-09-12T10:00:00",
        "resolved_at": None,
        "kind": "sample_mount",
        "detail": "Mount holder B",
        "status": status,
        "resolver": None,
        "resolver_note": None,
        "slack_channel": None,
        "slack_ts": None,
    }
    row.update(over)
    return row


class _FastAsyncio:
    """Proxy for the `asyncio` module that collapses the watcher's 2s poll.

    Only `sleep` is overridden; everything else (Event, Lock, wait,
    create_task, FIRST_COMPLETED) falls through to the real module, so the
    coordinator's concurrency is exercised as written.
    """

    def __init__(self, delay: float = 0.001):
        self._delay = delay
        self.requested: list[float] = []

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, delay, *args, **kwargs):
        self.requested.append(delay)
        return await asyncio.sleep(self._delay, *args, **kwargs)


@pytest.fixture
def harness(monkeypatch):
    """Patch the coordinator's DB seam and make its poll interval instant."""
    state: dict = {"rows": [], "polls": 0, "resolved": []}

    def _get_intervention(_row_id):
        state["polls"] += 1
        rows = state["rows"]
        # Last entry repeats once the script is exhausted.
        idx = min(state["polls"] - 1, len(rows) - 1)
        return rows[idx] if rows else None

    def _resolve_intervention(row_id, *, status, resolver, note=None):
        state["resolved"].append(
            {"id": row_id, "status": status, "resolver": resolver, "note": note}
        )

    async def _notify(_row_id, _detail):
        return None

    fast = _FastAsyncio()
    monkeypatch.setattr(staff_guidance, "asyncio", fast)
    monkeypatch.setattr(
        staff_guidance, "create_intervention",
        lambda experiment_id, kind, detail: _Row(),
    )
    monkeypatch.setattr(staff_guidance, "get_intervention", _get_intervention)
    monkeypatch.setattr(staff_guidance, "resolve_intervention", _resolve_intervention)

    state["fast"] = fast
    state["notify"] = _notify
    return state


def _request(harness, **over):
    kwargs = {
        "experiment_id": "exp-1",
        "kind": "sample_mount",
        "detail": "Mount holder B",
        "notify": harness["notify"],
    }
    kwargs.update(over)
    coordinator = staff_guidance.StaffCoordinator()
    return asyncio.run(coordinator.request_intervention(**kwargs))


def test_watcher_does_not_return_while_row_is_waiting(harness):
    """A `waiting` row is not a resolution: the wait must time out instead."""
    harness["rows"] = [_db_row("waiting")]

    result = _request(harness, timeout_s=0.2)

    # Before the fix the first poll returned {"status": "waiting"} and the
    # agent carried on as though a human had answered.
    assert result["status"] == "timed_out"
    assert result["resolver"] == "system"
    assert harness["polls"] > 1, "watcher should have polled repeatedly"
    assert harness["resolved"] == [
        {
            "id": "intv-1",
            "status": "timed_out",
            "resolver": "system",
            "note": "no response within 0.2s",
        }
    ]


def test_watcher_returns_once_row_is_resolved(harness):
    """Once staff resolve the row, the poll wakes the caller with it."""
    harness["rows"] = [
        _db_row("waiting"),
        _db_row("waiting"),
        _db_row(
            "resolved",
            resolver="staff_jane",
            resolver_note="holder B mounted",
            resolved_at="2026-09-12T10:05:00",
        ),
    ]

    result = _request(harness, timeout_s=5.0)

    assert result["status"] == "resolved"
    assert result["resolver"] == "staff_jane"
    assert result["id"] == "intv-1"
    assert harness["polls"] >= 3, "watcher returned before the row changed"
    assert harness["resolved"] == [], "no timeout resolution should be written"


def test_watcher_keeps_the_two_second_cadence(harness):
    """The poll interval is the documented human-scale 2s, not a busy loop."""
    harness["rows"] = [_db_row("waiting")]

    _request(harness, timeout_s=0.05)

    assert harness["fast"].requested, "watcher never slept"
    assert set(harness["fast"].requested) == {2.0}


def test_missing_row_does_not_end_the_wait(harness):
    """A row the DB cannot see yet is not a resolution either."""
    harness["rows"] = []  # get_intervention returns None forever

    result = _request(harness, timeout_s=0.2)

    assert result["status"] == "timed_out"
    assert harness["polls"] > 1
