"""Autonomous Beamline Agent tool system.

Public surface:

  * `TOOL_DEFINITIONS` — JSON-schema definitions for every tool the LLM can call.
  * `TOOL_CATEGORIES` — CAT-0..CAT-9 groupings for the UI sidebar.
  * `CLI_TOOL_DEFINITION` — progressive-discovery CLI tool (TOOLS_MODE=cli).
  * `execute_tool(name, args)` — dispatch to a tool's Python implementation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from beamline_tools.tool_catalog.definitions import (
    AUTONOMY_TOOL_CATEGORIES as _BASE_CATEGORIES,
    AUTONOMY_TOOL_DEFINITIONS as _BASE_TOOLS,
)
from beamline_tools.tool_catalog.cli_tool import CLI_TOOL_DEFINITION
from beamline_tools.tool_catalog.executor import execute_tool

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


TOOL_DEFINITIONS: list[dict] = _filter(_BASE_TOOLS)
TOOL_CATEGORIES = list(_BASE_CATEGORIES)


__all__ = [
    "CLI_TOOL_DEFINITION",
    "TOOL_CATEGORIES",
    "TOOL_DEFINITIONS",
    "execute_tool",
]
