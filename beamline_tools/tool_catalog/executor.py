"""Tool executor — dispatches tool calls to underlying beamline_tools modules.

Returns (result_text, images_b64) for each tool invocation.

The CLI's ``execute_tool`` grew a leading ``tree`` argument in Phase 2 so
the same tool name can coexist under different trees (``s3df.list_scans``
vs. ``spec-file.list_scans``). Autonomy doesn't yet need that
disambiguation — its DISPATCH is name-keyed and the autonomy-specific
tool names are unique — so we accept both the new 3-arg form and the
legacy 2-arg form and resolve by name. If a tree is given, we still try
it first (in case the autonomy team later registers tree-keyed handlers).
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

logger = logging.getLogger(__name__)


def _validate_args(name: str, arguments: dict) -> str | None:
    """Boundary-validate CAT-8 tool arguments against their pydantic model.

    Returns an ``{"ok": false, ...}`` JSON envelope string on validation
    failure (field-level errors the LLM can act on), or ``None`` when the
    arguments are valid or the tool has no registered model (the 82
    upstream tools are dispatched unvalidated, as before).
    """
    try:
        from beamline_tools.tool_catalog.arg_models import ARG_MODELS
    except Exception:
        return None
    model_cls = ARG_MODELS.get(name)
    if model_cls is None:
        return None
    try:
        model_cls.model_validate(arguments)
    except ValidationError as e:
        details = [
            "{}: {}".format(
                ".".join(str(p) for p in err["loc"]) or "(root)", err["msg"]
            )
            for err in e.errors()
        ]
        return json.dumps({
            "ok": False,
            "error": "invalid arguments",
            "details": details,
        })
    return None


def execute_tool(*posargs, **kw) -> tuple[str, list[str]]:
    """Dispatch a tool call. Returns ``(result_text, images_b64)``.

    Accepts either ``execute_tool(tree, name, arguments)`` (new CLI form)
    or ``execute_tool(name, arguments)`` (legacy form).
    """
    tree: tuple[str, ...] | None = None
    if len(posargs) == 3:
        tree_arg, name, arguments = posargs
        tree = tuple(tree_arg) if not isinstance(tree_arg, str) else (tree_arg,)
    elif len(posargs) == 2:
        name, arguments = posargs
    elif len(posargs) == 1:
        name = posargs[0]
        arguments = kw.get("arguments") or kw.get("args")
    else:
        raise TypeError(f"execute_tool: unexpected arg count: {len(posargs)}")

    try:
        from beamline_tools.tool_catalog.tools import DISPATCH
    except Exception:
        DISPATCH = {}

    fn = None
    if tree is not None:
        # Defensive: if a future autonomy DISPATCH ever becomes tree-keyed,
        # try that first before falling back to the name-only path.
        fn = DISPATCH.get(tree + (name,)) if isinstance(next(iter(DISPATCH), None), tuple) else None
    if fn is None:
        fn = DISPATCH.get(name)
    if fn is None:
        return f"Unknown tool: {name}", []
    # Boundary validation for CAT-8 tools only (name in ARG_MODELS).
    # The handler still receives the ORIGINAL arguments dict.
    error_envelope = _validate_args(name, arguments or {})
    if error_envelope is not None:
        return error_envelope, []
    try:
        text, imgs = fn(arguments or {})
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Tool error ({name}): {e}", []
    # Best-effort ScanRecord capture for scan-emitting actions. Cheap
    # substring gate first so non-action tools pay nothing.
    if isinstance(text, str) and '"action_id"' in text:
        try:
            from beamline_tools.scan_capture import capture_scan_record
            capture_scan_record(name, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("scan_capture hook failed for %s: %s", name, e)
    return text, list(imgs or [])
