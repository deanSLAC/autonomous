"""beamline_tools — autonomy-side extensions on top of beamtimehero_cli.

Most of what used to live in this package now comes from `beamtimehero_cli`
(installed as an editable local dependency). This namespace retains only
the autonomy-specific layer:

  * `agent_roles` — per-agent-role motor + spec-write allowlists used by
    `scripts/beamtimehero`.
  * `audited_call` — thin re-export of upstream `beamtimehero_cli.audited_call`
    (kept for import-compatibility).
  * `config` — re-exports upstream config + adds autonomy-only paths
    (CONTEXT_DIR, PLANS_DIR, OPENCODE_DIR, OPENCODE_TOOLS_DIR).
  * `spec_control` — re-exports upstream transport/clients/phases/spec_cmd.
  * `tool_catalog` — autonomy-side tool surface (CAT-8+ orchestration tools)
    plus the per-experiment tools_config.json enable/disable filter; sources
    upstream's tools_core for the generic catalog.
  * `steering` — autonomy-only intervention queue surface.

Existing consumers using `from beamline_tools.* import ...` keep working for
the modules above. For the generic CLI surface (action_log, spec_data,
spec_logs, generic_data, experiment_planning, spec_eval, transport clients),
import directly from `beamtimehero_cli.*`.
"""

from beamline_tools.audited_call import audited_call
from beamtimehero_cli.spec_control import spec_cmd
from beamtimehero_cli.spec_control import phases
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
    "phases",
    "spec_cmd",
]
