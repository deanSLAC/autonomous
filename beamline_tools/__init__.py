"""beamline_tools — SPEC tools, action/query log, scan data.

This package is the lift-and-drop layer: it has no dependencies on the
orchestration or UI packages and can be vendored into a future project
with only the requirements in `requirements.txt` that cover SPEC +
sqlite + numpy/silx.

Layout (grouped by source):

  * `spec_control/`       — SPEC direct interaction (screen / TCP transports,
                            phase constants + agent-role allowlists,
                            dispatcher, action_log writer)
  * `spec_logs/`          — SPEC session log files: list, tail, search,
                            parse, error-detect
  * `spec_data/`          — Raw SPEC data files (silx-readable): reader,
                            metadata cache, scan ops, plotting, on-disk
                            SPEC config parser
  * `generic_data/`       — Pure-math tools that operate on numpy arrays:
                            fitting, cosine similarity
  * `experiment_planning/` — Higher-level domain logic: scan→motor decisions,
                            motor strategies, scan efficiency / recommendations
  * `tool_catalog/`       — Agent-facing tool surface: schemas, executor,
                            CLI mode, lineage

Public API:

  * `audited_call` — phase/experiment/audit-aware SPEC dispatch (what tool
    handlers normally use)
  * `spec_cmd.call` — primitive SPEC dispatch (no audit, no phase)
  * `phases` — phase vocabulary + agent-role motor/spec-write allowlists
  * `action_log` writers and readers
  * `tool_catalog.TOOL_DEFINITIONS` + `execute_tool`
  * `spec_data.local_data`, `config.set_scan_dir`, `spec_data.spec_reader`
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
from beamline_tools.audited_call import audited_call
from beamline_tools.spec_control import phases, spec_cmd
from beamline_tools.tool_catalog import (
    CLI_TOOL_DEFINITION,
    TOOL_CATEGORIES,
    TOOL_DEFINITIONS,
    execute_tool,
)

__all__ = [
    "CLI_TOOL_DEFINITION",
    "TOOL_CATEGORIES",
    "TOOL_DEFINITIONS",
    "audited_call",
    "execute_tool",
    "finish_action",
    "invalidate_for_experiment",
    "log_query",
    "mark_action_started",
    "phases",
    "recent_actions",
    "recent_queries",
    "spec_cmd",
    "start_action",
]
