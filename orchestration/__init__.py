"""orchestration — phase machine, planner, LLM agent, UI-facing surface.

Sits on top of `beamline_tools`. The UI talks to this package only via
`orchestration.api` (and the routers that consume it).
"""

# Importing this package reaches beamtimehero_cli.config, so the deployment
# paths have to be pinned before that happens — this was the import that beat
# the bootstrap and sent the action log into the toolbelt's checkout.
import deployment_paths  # noqa: F401

from orchestration import api, config
from orchestration.plan_store.init_db import init_db

__all__ = ["api", "config", "init_db"]
