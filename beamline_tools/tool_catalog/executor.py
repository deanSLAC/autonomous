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

import logging

logger = logging.getLogger(__name__)


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
    try:
        text, imgs = fn(arguments or {})
        return text, list(imgs or [])
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Tool error ({name}): {e}", []
