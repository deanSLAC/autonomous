"""Executor-level boundary validation for CAT-8 tools.

`execute_tool` validates arguments against the pydantic model registered
in `arg_models.ARG_MODELS` BEFORE dispatch:

  * valid args → handler called with the ORIGINAL dict (not a model);
  * invalid args → structured `{"ok": false, "error": "invalid
    arguments", "details": [...]}` envelope, handler NOT called;
  * extra/unknown args → pass through untouched (extra="allow");
  * tools without a registered model (the ~101 upstream ones) dispatch
    unvalidated, exactly as before.

The validation is now a `BeforeHook` on upstream's `make_executor`
(`executor._validate_args_hook`) rather than an inline branch, which is
what lets an agent surface install the identical check on its own
restricted executor. The behaviour it pins is unchanged.
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


def _capture(calls):
    def handler(args):
        calls.append(args)
        return json.dumps({"ok": True}), []
    return handler


def test_valid_args_dispatch_to_handler(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "record_sample_progress"), _capture(calls))
    text, images = execute_tool(("db",), "record_sample_progress",
                                {"sample_id": "s1", "status": "done"})
    assert json.loads(text) == {"ok": True}
    assert images == []
    assert calls == [{"sample_id": "s1", "status": "done"}]


def test_missing_required_field_returns_envelope_naming_field(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "record_sample_progress"), _capture(calls))
    text, images = execute_tool(("db",), "record_sample_progress", {"status": "done"})
    body = json.loads(text)
    assert body["ok"] is False
    assert body["error"] == "invalid arguments"
    assert any(d.startswith("sample_id:") for d in body["details"])
    assert images == []
    assert calls == []  # handler never invoked


def test_wrong_type_returns_envelope(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "update_plan"), _capture(calls))
    text, _ = execute_tool(("db",), "update_plan", {"plan": 42})
    body = json.loads(text)
    assert body["ok"] is False
    assert body["error"] == "invalid arguments"
    assert any(d.startswith("plan:") for d in body["details"])
    assert calls == []


def test_extra_args_pass_through_unchanged(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "record_sample_progress"), _capture(calls))
    args = {"sample_id": "s1", "totally_unknown_arg": [1, 2, 3]}
    text, _ = execute_tool(("db",), "record_sample_progress", args)
    assert json.loads(text) == {"ok": True}
    # Handler receives the ORIGINAL dict, extra key included.
    assert calls == [args]


def test_none_arguments_validates_as_empty_dict(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "get_plan"), _capture(calls))
    text, _ = execute_tool(("db",), "get_plan", None)
    assert json.loads(text) == {"ok": True}
    assert calls == [{}]


def test_none_arguments_on_required_tool_returns_envelope(monkeypatch):
    calls = []
    monkeypatch.setitem(DISPATCH, ("db", "update_plan"), _capture(calls))
    text, _ = execute_tool(("db",), "update_plan", None)
    body = json.loads(text)
    assert body["ok"] is False
    assert any(d.startswith("plan:") for d in body["details"])
    assert calls == []


def test_tools_without_model_skip_validation(monkeypatch):
    """Upstream tools (not in ARG_MODELS) must dispatch unvalidated."""
    calls = []
    monkeypatch.setitem(DISPATCH, ("tool", "not_a_cat8_tool"), _capture(calls))
    text, _ = execute_tool(("tool",), "not_a_cat8_tool", {"anything": "goes"})
    assert json.loads(text) == {"ok": True}
    assert calls == [{"anything": "goes"}]


def test_validation_is_keyed_by_name_not_tree(monkeypatch):
    """The arg model is looked up by tool name, so the same check applies
    wherever a surface has placed the leaf."""
    calls = []
    monkeypatch.setitem(DISPATCH, ("tool", "record_sample_progress"), _capture(calls))
    text, _ = execute_tool(("tool",), "record_sample_progress", {})
    body = json.loads(text)
    assert body["ok"] is False
    assert body["error"] == "invalid arguments"
    assert calls == []
