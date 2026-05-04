"""Autonomous Beamline Agent tool system.

Public surface:

  * `TOOL_DEFINITIONS` — JSON-schema definitions for every tool the LLM can call.
  * `AUTONOMY_TOOL_DEFINITIONS` / `AUTONOMY_TOOL_CATEGORIES` — grouped by CAT.
  * `CLI_TOOL_DEFINITION` — progressive-discovery CLI tool (TOOLS_MODE=cli).
  * `execute_tool(name, args)` — dispatch to a tool's Python implementation.
  * `register(definition, fn)` — external packages (e.g. orchestration) add tools here.

Layered tools (anything that touches orchestrator / planner / plan_store)
register themselves at import time so this catalog stays free of
orchestration dependencies.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from beamline_tools.tool_catalog.autonomy_definitions import (
    AUTONOMY_TOOL_CATEGORIES as _BASE_AUTONOMY_CATEGORIES,
    AUTONOMY_TOOL_DEFINITIONS as _BASE_AUTONOMY_TOOLS,
)
from beamline_tools.tool_catalog.definitions import (
    CLI_TOOL_DEFINITION,
    TOOL_DEFINITIONS as _BT_TOOLS,
)
from beamline_tools.tool_catalog.executor import execute_tool, register_dispatch

_logger = logging.getLogger(__name__)

_TOOLS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "tools_config.json"


def _load_enabled_set() -> set[str] | None:
    """Return the set of enabled tool names, or None if config is absent (fail-open)."""
    if not _TOOLS_CONFIG_PATH.exists():
        return None
    try:
        with open(_TOOLS_CONFIG_PATH) as f:
            data = json.load(f)
        return {t["name"] for t in data.get("tools", []) if t.get("enabled", True)}
    except Exception:
        _logger.warning("Could not read %s — all tools enabled", _TOOLS_CONFIG_PATH)
        return None


_enabled = _load_enabled_set()


def _filter(defs: list[dict]) -> list[dict]:
    if _enabled is None:
        return list(defs)
    return [d for d in defs if d["function"]["name"] in _enabled]


# Mutable — orchestration extends it at import-time via `register()`.
TOOL_DEFINITIONS: list[dict] = _filter(_BT_TOOLS) + _filter(_BASE_AUTONOMY_TOOLS)
AUTONOMY_TOOL_DEFINITIONS: list[dict] = _filter(_BASE_AUTONOMY_TOOLS)
AUTONOMY_TOOL_CATEGORIES = list(_BASE_AUTONOMY_CATEGORIES)


def register(definition: dict, fn) -> None:
    """Add an externally-owned tool to the catalog.

    `definition` is the JSON-schema dict; `fn` is the Python callable
    matching the signature `fn(args: dict) -> tuple[str, list[str]]`.
    """
    name = definition["function"]["name"]
    if _enabled is not None and name not in _enabled:
        return
    TOOL_DEFINITIONS.append(definition)
    AUTONOMY_TOOL_DEFINITIONS.append(definition)
    register_dispatch(name, fn)


__all__ = [
    "AUTONOMY_TOOL_CATEGORIES",
    "AUTONOMY_TOOL_DEFINITIONS",
    "CLI_TOOL_DEFINITION",
    "TOOL_DEFINITIONS",
    "execute_tool",
    "register",
]
