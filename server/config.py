"""Shared configuration for the Autonomous Beamline Agent.

Backend: opencode (local server) against the SLAC AI Gateway. No
Stanford AI endpoint; no other provider. One path.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
STATIC_DIR = PROJECT_ROOT / "static"
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
OPENCODE_DIR = PROJECT_ROOT / ".opencode"
OPENCODE_TOOLS_DIR = OPENCODE_DIR / "tools"
DATA_DIR.mkdir(exist_ok=True)

# ----- LLM backend: opencode + SLAC AI Gateway -----
# The SLAC key is the only LLM credential the app understands.
SLAC_API_KEY = os.getenv("SLAC_API_KEY", "")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "slac/us.anthropic.claude-opus-4-6-v1")
OPENCODE_URL = os.getenv("OPENCODE_URL", "http://127.0.0.1:4096")
OPENCODE_USERNAME = os.getenv("OPENCODE_USERNAME", "")
OPENCODE_PASSWORD = os.getenv("OPENCODE_PASSWORD", "")
OPENCODE_TIMEOUT_S = float(os.getenv("OPENCODE_TIMEOUT_S", "600"))

# Slack
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
SLACK_LLM_CHANNEL_ID = os.getenv("SLACK_LLM_CHANNEL_ID", "")
SLACK_USERS_CHANNEL_ID = os.getenv("SLACK_USERS_CHANNEL_ID", "")
SLACK_STAFF_CHANNEL_ID = os.getenv("SLACK_STAFF_CHANNEL_ID", "")

# App
BASE_PATH = os.getenv("BASE_PATH", "")
PORT = int(os.getenv("PORT", "8080"))

# Autonomous database
DB_PATH = os.getenv("AUTONOMOUS_DB_PATH", str(DATA_DIR / "autonomous.db"))
os.environ.setdefault("BEAMLINE_DB_PATH", DB_PATH)

# SPEC screen + dispatcher
SPEC_SCREEN_NAME = os.getenv("SPEC_SCREEN_NAME", "spec")
SPEC_POLL_INTERVAL_S = float(os.getenv("SPEC_POLL_INTERVAL_S", "2.0"))
SPEC_PROMPT_REGEX = os.getenv("SPEC_PROMPT_REGEX", r"^\d+\.SPEC> ?$")
SPEC_MOCK = os.getenv("SPEC_MOCK", "0") == "1"

# Orchestrator cadences
ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "1") == "1"
ORCHESTRATOR_TICK_S = float(os.getenv("ORCHESTRATOR_TICK_S", "5.0"))
STATUS_POST_INTERVAL_S = float(os.getenv("STATUS_POST_INTERVAL_S", "900"))
DEFAULT_BEAMTIME_HOURS = float(os.getenv("DEFAULT_BEAMTIME_HOURS", "48"))
BACKWARD_ONE_TIMEOUT_S = float(os.getenv("BACKWARD_ONE_TIMEOUT_S", "60"))
BACKWARD_MANY_TIMEOUT_S = float(os.getenv("BACKWARD_MANY_TIMEOUT_S", "30"))
GAP_REQUEST_TIMEOUT_S = float(os.getenv("GAP_REQUEST_TIMEOUT_S", "900"))

# EPICS PVs (reference only)
EPICS_PV_SPEAR_CURRENT = os.getenv("EPICS_PV_SPEAR_CURRENT", "SPEAR:BeamCurrAvg")
EPICS_PV_BL_STATE = os.getenv("EPICS_PV_BL_STATE", "BL15:State")
EPICS_PV_GAP_OWNER = os.getenv("EPICS_PV_GAP_OWNER", "BL15:GapOwnerNode")


def llm_enabled() -> bool:
    """True iff the LLM backend is usable (key present + opencode URL set)."""
    return bool(SLAC_API_KEY) and bool(OPENCODE_URL)
