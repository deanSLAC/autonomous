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

from beamline_tools.tool_catalog.autonomy_definitions import (
    AUTONOMY_TOOL_CATEGORIES as _BASE_AUTONOMY_CATEGORIES,
    AUTONOMY_TOOL_DEFINITIONS as _BASE_AUTONOMY_TOOLS,
)
from beamline_tools.tool_catalog.definitions import (
    CLI_TOOL_DEFINITION,
    TOOL_DEFINITIONS as _BT_TOOLS,
)
from beamline_tools.tool_catalog.executor import execute_tool, register_dispatch

# Mutable — orchestration extends it at import-time via `register()`.
TOOL_DEFINITIONS: list[dict] = list(_BT_TOOLS) + list(_BASE_AUTONOMY_TOOLS)
AUTONOMY_TOOL_DEFINITIONS: list[dict] = list(_BASE_AUTONOMY_TOOLS)
AUTONOMY_TOOL_CATEGORIES = list(_BASE_AUTONOMY_CATEGORIES)


def register(definition: dict, fn) -> None:
    """Add an externally-owned tool to the catalog.

    `definition` is the JSON-schema dict; `fn` is the Python callable
    matching the signature `fn(args: dict) -> tuple[str, list[str]]`.
    """
    name = definition["function"]["name"]
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
