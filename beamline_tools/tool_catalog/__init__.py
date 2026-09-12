"""Autonomous Beamline Agent tool system.

Registers autonomy's CAT-8 orchestration overlay into upstream's
`beamtimehero_cli.tool_catalog` (CAT-0..CAT-7, CAT-9, CAT-10) rather than
concatenating a private copy beside it.

Public surface:

  * `TOOL_DEFINITIONS` — upstream's list, with autonomy's CAT-8 tools
    appended. The *same list object* upstream holds, so `categorize()`,
    `build_catalog_subtrees()` and `Catalogue.default()` all see the
    whole catalog with nothing patched.
  * `TOOL_CATEGORIES` — CAT-0..CAT-10 groupings for the UI sidebar.
  * `CLI_TOOL_DEFINITION` — progressive-discovery CLI tool (TOOLS_MODE=cli).
  * `execute_tool(tree, name, args)` — dispatch to a tool's Python
    implementation.

There is no enable/disable filter here any more. `tools_config.json`
remains the tool-tester UI's status document (`simulated`,
`working_live`, `comments`), but it is no longer a gate on what the
catalog contains: a tool that an agent must not reach is now absent from
that agent's surface (see `beamline_tools/agent_roles.py`), which is a
statement about one role rather than a process-wide edit that silently
changed what every role could see.
"""
from __future__ import annotations

from beamtimehero_cli.tool_catalog import (
    TOOL_DEFINITIONS,
    register_definitions,
)
from beamtimehero_cli.tool_catalog.cli_tool import CLI_TOOL_DEFINITION
from beamtimehero_cli.tool_catalog.definitions import (
    AUTONOMY_TOOL_CATEGORIES as _UPSTREAM_CATEGORIES,
)

# Importing this module registers autonomy's CAT-8 lineage entries into
# upstream's TOOL_LINEAGE, and that must happen before the definitions
# are registered below. `register_definitions()` dedupes by
# `categorize(d) + (name,)`, and `categorize()` reads lineage to decide
# that an `autonomy_db` tool belongs on `db`. With lineage registered
# first the path check is exact; the other way round, every CAT-8
# definition would be path-checked as `("tool", name)` — the wrong path,
# so the duplicate guard would be approximate.
from beamline_tools.tool_catalog import lineage as _lineage  # noqa: F401
from beamline_tools.tool_catalog.definitions import (
    AUTONOMY_TOOL_CATEGORIES as _AUTONOMY_CATEGORIES,
    AUTONOMY_TOOL_DEFINITIONS as _AUTONOMY_TOOLS,
)
from beamline_tools.tool_catalog.executor import execute_tool

register_definitions(_AUTONOMY_TOOLS)

# Category groupings concatenate the same way the definitions do, but
# autonomy owns CAT-8: upstream ships a stale CAT-8 stub that references
# tools it does not define.
TOOL_CATEGORIES = [
    c for c in _UPSTREAM_CATEGORIES if not c[0].startswith("CAT-8")
] + list(_AUTONOMY_CATEGORIES)


__all__ = [
    "CLI_TOOL_DEFINITION",
    "TOOL_CATEGORIES",
    "TOOL_DEFINITIONS",
    "execute_tool",
]
