"""Plan-validation tests for `replace_plan` / `t_update_plan`.

Goal: prove that during the `collection` phase, the planner cannot
write a plan whose every sample is in a terminal status
(`done`/`skipped`/`failed`) — that state is the deadlock that took
the system deaf in production.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.planner import planner  # noqa: E402
from beamline_tools.tool_catalog import autonomy_tools  # noqa: E402


@pytest.fixture
def stub_plan_store(monkeypatch):
    """Replace get_plan/upsert_experiment_plan with in-memory stubs.

    Returns a dict with `current_phase` (read by validation) and
    `last_write` (captured if the write was allowed through).
    """
    state = {"current_phase": "collection", "last_write": None}

    def fake_get_plan(experiment_id):
        return {"phase": state["current_phase"]}

    def fake_upsert(experiment_id, *, plan=None, **kw):
        state["last_write"] = plan

    monkeypatch.setattr(planner, "get_plan", fake_get_plan)
    monkeypatch.setattr(planner, "upsert_experiment_plan", fake_upsert)
    return state


def _plan_with_statuses(*statuses: str) -> dict:
    return {
        "sample_queue": [
            {"sample_id": f"s{i}", "status": s} for i, s in enumerate(statuses)
        ],
    }


def test_all_done_during_collection_raises(stub_plan_store):
    plan = _plan_with_statuses("done", "done", "skipped", "failed")
    with pytest.raises(planner.PlanValidationError):
        planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is None


def test_at_least_one_in_progress_passes(stub_plan_store):
    plan = _plan_with_statuses("done", "in_progress", "failed")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_at_least_one_queued_passes(stub_plan_store):
    plan = _plan_with_statuses("done", "queued", "skipped")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_all_done_during_setup_passes(stub_plan_store):
    stub_plan_store["current_phase"] = "setup"
    plan = _plan_with_statuses("done", "done", "done")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_all_done_during_complete_passes(stub_plan_store):
    stub_plan_store["current_phase"] = "complete"
    plan = _plan_with_statuses("done", "done", "skipped")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_no_current_plan_skips_validation(stub_plan_store, monkeypatch):
    monkeypatch.setattr(planner, "get_plan", lambda _eid: None)
    plan = _plan_with_statuses("done", "done")
    planner.replace_plan("exp-1", plan)
    assert stub_plan_store["last_write"] is not None


def test_empty_sample_queue_during_collection_raises(stub_plan_store):
    plan = {"sample_queue": []}
    with pytest.raises(planner.PlanValidationError):
        planner.replace_plan("exp-1", plan)


def test_t_update_plan_returns_error_envelope(stub_plan_store, monkeypatch):
    monkeypatch.setattr(autonomy_tools.spec_cmd, "get_experiment_id",
                        lambda: "exp-1")
    # Suppress the best-effort plan_summary side-effect; not under test.
    import orchestration.planner.plan_summary as plan_summary_mod
    monkeypatch.setattr(plan_summary_mod, "generate_and_post",
                        lambda _eid: None)

    plan = _plan_with_statuses("done", "skipped", "failed")
    body_json, _ = autonomy_tools.t_update_plan({"plan": plan})
    body = json.loads(body_json)
    assert body["ok"] is False
    assert "zero actionable samples" in body["error"]


def test_t_update_plan_returns_ok_on_valid_plan(stub_plan_store, monkeypatch):
    monkeypatch.setattr(autonomy_tools.spec_cmd, "get_experiment_id",
                        lambda: "exp-1")
    import orchestration.planner.plan_summary as plan_summary_mod
    monkeypatch.setattr(plan_summary_mod, "generate_and_post",
                        lambda _eid: None)

    plan = _plan_with_statuses("in_progress", "queued")
    body_json, _ = autonomy_tools.t_update_plan({"plan": plan})
    body = json.loads(body_json)
    assert body["ok"] is True
