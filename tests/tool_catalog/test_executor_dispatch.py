"""Smoke tests for tool-catalog dispatch.

Pins execute_tool's contract (name-keyed + tree-keyed resolution, error
envelopes) and the CAT-8 update_plan argument handling before the
opencode-removal refactor. Object args MUST work as real dicts — that is
what the `beamtimehero` CLI delivers (argparse json.loads at parse time)
and what must keep working when the opencode JSON-string unwrap shims
are removed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.tool_catalog import tools  # noqa: E402
from beamline_tools.tool_catalog.executor import execute_tool  # noqa: E402


def test_unknown_tool_returns_error_string():
    text, images = execute_tool("definitely_not_a_tool", {})
    assert "Unknown tool" in text
    assert images == []


def test_handler_exception_is_contained(monkeypatch):
    def boom(args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(tools.DISPATCH, "boom_tool", boom)
    text, images = execute_tool("boom_tool", {})
    assert text.startswith("Tool error (boom_tool)")
    assert "kaboom" in text
    assert images == []


def test_name_keyed_dispatch_two_arg_form(monkeypatch):
    monkeypatch.setitem(
        tools.DISPATCH, "echo_tool", lambda args: (json.dumps(args), []),
    )
    text, images = execute_tool("echo_tool", {"x": 1})
    assert json.loads(text) == {"x": 1}


def test_three_arg_form_resolves_by_name(monkeypatch):
    monkeypatch.setitem(
        tools.DISPATCH, "echo_tool", lambda args: (json.dumps(args), []),
    )
    text, _ = execute_tool(("tool",), "echo_tool", {"y": 2})
    assert json.loads(text) == {"y": 2}


def test_cat8_tools_are_registered():
    # A representative slice of the autonomy CAT-8 surface.
    for name in ("update_plan", "get_comprehensive_collection_plan",
                 "record_sample_progress"):
        assert name in tools.DISPATCH, f"{name} missing from DISPATCH"


def test_update_plan_accepts_dict_args(monkeypatch):
    """Object args arrive as parsed dicts via the CLI — must keep working."""
    monkeypatch.setattr(tools.runtime_state, "get_experiment_id", lambda: "exp-1")

    captured = {}

    def fake_replace_plan(experiment_id, plan):
        captured["experiment_id"] = experiment_id
        captured["plan"] = plan

    monkeypatch.setattr(tools.planner, "replace_plan", fake_replace_plan)
    import orchestration.planner.plan_summary as plan_summary_mod
    monkeypatch.setattr(plan_summary_mod, "generate_and_post", lambda _eid: None)

    plan = {"sample_queue": [{"sample_id": "s1", "status": "queued"}]}
    text, images = tools.t_update_plan({"plan": plan})
    body = json.loads(text)
    assert body["ok"] is True
    assert captured["plan"] == plan
    assert captured["experiment_id"] == "exp-1"


def test_update_plan_rejects_non_object_plan(monkeypatch):
    monkeypatch.setattr(tools.runtime_state, "get_experiment_id", lambda: "exp-1")
    text, _ = tools.t_update_plan({"plan": 42})
    body = json.loads(text)
    assert body["ok"] is False
