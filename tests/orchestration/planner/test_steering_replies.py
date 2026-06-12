"""Tick step 4: completed steering rows reply into their Slack thread.

Agents close steering rows with `steering complete <id> --result ...`;
the orchestrator tick must relay that result to the originating Slack
thread exactly once (stamping slack_replied_at via mark_steering_replied).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.planner import loop, orchestrator_tick  # noqa: E402


def _row(**over):
    base = {
        "id": "st-1",
        "result": "calibrate_mono rerun, residual now 0.08 eV",
        "slack_channel": "C123",
        "slack_thread_ts": "1718000000.000100",
    }
    base.update(over)
    return base


@pytest.fixture
def harness(monkeypatch):
    posted: list[tuple] = []
    marked: list[str] = []
    state = {"rows": []}

    orch = loop.Orchestrator(
        slack_post_steering_reply=lambda c, t, s: posted.append((c, t, s)),
    )
    monkeypatch.setattr(loop, "get_orchestrator", lambda: orch)
    monkeypatch.setattr(
        orchestrator_tick, "list_completed_unposted_steering",
        lambda experiment_id: state["rows"],
    )
    monkeypatch.setattr(
        orchestrator_tick, "mark_steering_replied",
        lambda sid: marked.append(sid),
    )
    return {"posted": posted, "marked": marked, "state": state}


def test_completed_row_posts_to_thread_and_marks_replied(harness):
    harness["state"]["rows"] = [_row()]
    asyncio.run(orchestrator_tick._step_post_steering_replies("exp-1"))
    assert harness["posted"] == [
        ("C123", "1718000000.000100", "✅ calibrate_mono rerun, residual now 0.08 eV"),
    ]
    assert harness["marked"] == ["st-1"]


def test_no_rows_is_a_no_op(harness):
    asyncio.run(orchestrator_tick._step_post_steering_replies("exp-1"))
    assert harness["posted"] == []
    assert harness["marked"] == []


def test_missing_result_text_uses_placeholder(harness):
    harness["state"]["rows"] = [_row(result=None)]
    asyncio.run(orchestrator_tick._step_post_steering_replies("exp-1"))
    assert harness["posted"][0][2].startswith("✅ (steering item completed")
    assert harness["marked"] == ["st-1"]


def test_uninitialized_orchestrator_leaves_rows_queued(harness, monkeypatch):
    monkeypatch.setattr(loop, "get_orchestrator", lambda: None)
    harness["state"]["rows"] = [_row()]
    asyncio.run(orchestrator_tick._step_post_steering_replies("exp-1"))
    assert harness["posted"] == []
    assert harness["marked"] == []  # not marked — retried next tick
