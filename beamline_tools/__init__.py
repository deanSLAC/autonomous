"""beamline_tools — SPEC tools, action/query log, scan data.

This package is the lift-and-drop layer: it has no dependencies on the
orchestration or UI packages and can be vendored into a future project
with only the requirements in `requirements.txt` that cover SPEC +
sqlite + numpy/silx.

Public API:

  * `spec_cmd.call/read` + context accessors (`get_phase`, `get_experiment_id`)
  * `phase_allowlist.is_allowed`
  * `action_log` writers and readers
  * `tool_catalog.TOOL_DEFINITIONS` + `execute_tool` + `register`
  * `scans.local_data`, `scans.bl_config.set_scan_dir`, `scans.spec_reader`
"""

from beamline_tools.action_log import (
    finish_action,
    invalidate_for_experiment,
    log_query,
    mark_action_started,
    recent_actions,
    recent_queries,
    start_action,
)
from beamline_tools.spec import phase_allowlist, spec_cmd
from beamline_tools.tool_catalog import (
    AUTONOMY_TOOL_CATEGORIES,
    AUTONOMY_TOOL_DEFINITIONS,
    CLI_TOOL_DEFINITION,
    TOOL_DEFINITIONS,
    execute_tool,
    register,
)

__all__ = [
    "AUTONOMY_TOOL_CATEGORIES",
    "AUTONOMY_TOOL_DEFINITIONS",
    "CLI_TOOL_DEFINITION",
    "TOOL_DEFINITIONS",
    "execute_tool",
    "finish_action",
    "invalidate_for_experiment",
    "log_query",
    "mark_action_started",
    "phase_allowlist",
    "recent_actions",
    "recent_queries",
    "register",
    "spec_cmd",
    "start_action",
]
