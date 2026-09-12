"""Smoke tests for tool-catalog dispatch.

Pins `execute_tool`'s contract — tree-keyed resolution and the error
envelopes — plus the CAT-8 `update_plan` argument handling. Object args
MUST work as real dicts: that is what the `beamtimehero` CLI delivers
(argparse `json.loads` at parse time).

The table is upstream's `tools_core.DISPATCH`, keyed by
`(tree, ..., name)`. Autonomy used to keep a name-keyed flatten of it,
which forced a hand-coded "spec-file wins" rule for the six leaf names
that exist on both `spec-file` and `s3df`. Registering into the tree-keyed
table keeps those six pairs distinct, so the two tests at the bottom of
this file changed from "the right handler won the collision" to "there is
no collision".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.tool_catalog import tools  # noqa: E402,F401 — registers CAT-8
from beamline_tools.tool_catalog.executor import execute_tool  # noqa: E402
from beamtimehero_cli.tool_catalog.tools_core import DISPATCH  # noqa: E402


def test_unknown_tool_returns_error_string():
    text, images = execute_tool(("tool",), "definitely_not_a_tool", {})
    assert text == "Unknown tool: tool/definitely_not_a_tool"
    assert images == []


def test_known_name_on_the_wrong_tree_is_unknown():
    """The path is the identity: a real tool asked for on a tree it does
    not live on is not silently resolved by name."""
    text, _ = execute_tool(("spec-write",), "get_plan", {})
    assert text == "Unknown tool: spec-write/get_plan"


def test_handler_exception_is_contained(monkeypatch):
    def boom(args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(DISPATCH, ("tool", "boom_tool"), boom)
    text, images = execute_tool(("tool",), "boom_tool", {})
    assert text.startswith("Tool error (tool/boom_tool)")
    assert "kaboom" in text
    assert images == []


def test_tree_keyed_dispatch(monkeypatch):
    monkeypatch.setitem(
        DISPATCH, ("tool", "echo_tool"), lambda args: (json.dumps(args), []),
    )
    text, _ = execute_tool(("tool",), "echo_tool", {"x": 1})
    assert json.loads(text) == {"x": 1}


def test_bare_string_tree_is_accepted(monkeypatch):
    """A single-segment branch may be passed as a plain string."""
    monkeypatch.setitem(
        DISPATCH, ("tool", "echo_tool"), lambda args: (json.dumps(args), []),
    )
    text, _ = execute_tool("tool", "echo_tool", {"y": 2})
    assert json.loads(text) == {"y": 2}


def test_nested_tree_dispatch(monkeypatch):
    """Multi-segment branches (s3df psql) key on the whole path."""
    monkeypatch.setitem(
        DISPATCH, ("s3df", "psql", "probe"), lambda args: ("ok", []),
    )
    text, _ = execute_tool(("s3df", "psql"), "probe", {})
    assert text == "ok"


def test_cat8_tools_are_registered():
    # A representative slice of the autonomy CAT-8 surface, on `db` —
    # where `source: "autonomy_db"` puts it.
    for name in ("update_plan", "get_comprehensive_collection_plan",
                 "record_sample_progress"):
        assert ("db", name) in DISPATCH, f"{name} missing from DISPATCH"


def test_autonomy_handler_overrides_the_upstream_spec_write_leaf():
    """A name-keyed registration replaces upstream's handler on whatever
    branch the definition sits on — autonomy's measure_beam_size records
    the result to the DB."""
    assert DISPATCH[("spec-write", "measure_beam_size")] is tools.t_measure_beam_size


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


def test_spec_file_and_s3df_handlers_stay_distinct():
    """s3df duplicates six spec-file leaf names. Both paths must resolve to
    their own backend: on the beamline a spec-file call must read the SPEC
    file, not silently hit Postgres."""
    for name in ("list_scans", "get_latest_scan", "read_scan",
                 "get_active_counter", "get_scan_deadtime", "plot_scan"):
        spec_file = DISPATCH.get(("spec-file", name))
        s3df = DISPATCH.get(("s3df", name))
        assert spec_file is not None, name
        assert s3df is not None, name
        assert spec_file is not s3df, name


def test_s3df_only_leaves_still_registered():
    s3df_only = {k[-1] for k in DISPATCH if k[0] == "s3df"} - {
        k[-1] for k in DISPATCH if k[0] != "s3df"
    }
    assert s3df_only, "expected at least the psql leaves to be s3df-only"
    for name in s3df_only:
        assert any(k[0] == "s3df" and k[-1] == name for k in DISPATCH), name
