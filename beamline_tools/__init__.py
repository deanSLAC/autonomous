"""beamline_tools — autonomy-side extensions on top of beamtimehero_cli.

Most of what used to live in this package now comes from `beamtimehero_cli`
(installed as an editable local dependency). This namespace retains only
the autonomy-specific layer:

  * `agent_roles` — per-agent-role motor + spec-write allowlists used by
    `scripts/beamtimehero`.
  * `audited_call` — thin re-export of upstream `beamtimehero_cli.audited_call`
    (kept for import-compatibility).
  * `config` — re-exports upstream config + adds autonomy-only paths
    (CONTEXT_DIR, PLANS_DIR).
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

# ---------------------------------------------------------------------------
# Deployment path bootstrap — MUST run before any beamtimehero_cli import.
#
# Upstream `beamtimehero_cli.config` reads these at import time. This package's
# __init__ imports audited_call (-> beamtimehero_cli.config) on the first line
# below, so setting them inside `beamline_tools/config.py` was too late: the
# action log and the SPEC safety switch both resolved into the *toolbelt's*
# checkout instead of this repo. Set them here, before the first import, and
# every entry point (scripts/beamtimehero, the UI server, the orchestrator)
# inherits the same answer.
# ---------------------------------------------------------------------------

import os as _os
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent.parent
_os.environ.setdefault("BEAMTIMEHERO_DATA_DIR", str(_REPO_ROOT / "data"))
_os.environ.setdefault(
    "BEAMTIMEHERO_SAFETY_SWITCHES",
    str(_REPO_ROOT / "beamline_tools" / "safety_switches.json"),
)

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
