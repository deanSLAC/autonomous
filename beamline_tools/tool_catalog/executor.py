"""Autonomy's executor: upstream's, plus two hooks.

`beamtimehero_cli.tool_catalog.executor.make_executor()` produces the
dispatch loop and the `Unknown tool: a/b` / `Tool error (a/b): e`
envelopes. This module supplies the two things that are autonomy's:

  * `_validate_args_hook` — a *before* hook that boundary-validates
    CAT-8 arguments against their pydantic model and refuses with a
    field-level `{"ok": false, ...}` envelope the LLM can act on.
  * `_scan_capture_hook` — an *after* hook that files a ScanRecord for
    scan-emitting actions.

Both are exported because an agent surface needs them: `build_surface(
spec, catalogue, before=(_validate_args_hook,), after=(_scan_capture_hook,))`
installs the same two hooks on the restricted executor, behind the motor
allow-list. That is the point of the hook shape — there is one definition
of "validate, then dispatch, then capture", and the guarded and
unguarded executors share it.

`execute_tool(tree, name, arguments)` is the unrestricted form, over
upstream's whole `(tree, ..., name)`-keyed table. The old 1- and 2-arg
name-keyed forms are gone; nothing outside this repo's tests called them.
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from beamtimehero_cli.tool_catalog.executor import make_executor

logger = logging.getLogger(__name__)


def _validate_args_hook(tree: tuple[str, ...], name: str, arguments: dict) -> str | None:
    """Boundary-validate CAT-8 tool arguments against their pydantic model.

    Returns an ``{"ok": false, ...}`` JSON envelope string on validation
    failure (field-level errors the LLM can act on), or ``None`` when the
    arguments are valid or the tool has no registered model — the ~101
    upstream tools are dispatched unvalidated, as before.
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


def _scan_capture_hook(tree: tuple[str, ...], name: str, text: str) -> None:
    """Best-effort ScanRecord capture for scan-emitting actions.

    An observer: it returns ``None`` so the tool's own result text is
    what the caller sees. The cheap substring gate comes first so
    non-action tools pay nothing.
    """
    if isinstance(text, str) and '"action_id"' in text:
        try:
            from beamline_tools.scan_capture import capture_scan_record
            capture_scan_record(name, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("scan_capture hook failed for %s: %s", name, e)
    return None


_EXECUTOR = None


def _executor():
    """Build the executor over upstream's DISPATCH, once.

    Two reasons this is lazy rather than a module-level
    ``execute_tool = make_executor(tools_core.DISPATCH, ...)``:

    * Importing ``beamline_tools.tool_catalog.tools`` is what registers
      the CAT-8 handlers, and that module imports ``beamline_tools``,
      which imports this one. At module level the import is a cycle; on
      first call it is not.
    * ``tools_core`` pulls in matplotlib and the science stack (+0.5s,
      ~700 modules). ``beamline_tools`` is imported by the UI server and
      by ``orchestration``, neither of which dispatches a tool.

    ``make_executor`` holds the table by reference and
    ``register_handlers`` mutates it in place, so one executor stays
    correct for the life of the process.
    """
    global _EXECUTOR
    if _EXECUTOR is None:
        from beamline_tools.tool_catalog import tools  # noqa: F401 — registers CAT-8
        from beamtimehero_cli.tool_catalog.tools_core import DISPATCH

        _EXECUTOR = make_executor(
            DISPATCH,
            before=(_validate_args_hook,),
            after=(_scan_capture_hook,),
        )
    return _EXECUTOR


def execute_tool(
    tree: tuple[str, ...] | str,
    name: str,
    arguments: dict,
) -> tuple[str, list[str]]:
    """Dispatch a tool call. Returns ``(result_text, images_b64)``."""
    return _executor()(tree, name, arguments)
