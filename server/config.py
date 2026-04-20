"""Shared configuration for the Autonomous Beamline Agent.

Philosophy: .env holds only secrets and external IDs (LLM key, Slack
tokens, channel IDs). Everything internal — port, paths, opencode
location, timing — lives here as a hardcoded default. The handful of
remaining env-var hooks are escape hatches for unusual deployments,
not knobs the user is expected to set.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
STATIC_DIR = PROJECT_ROOT / "static"
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
OPENCODE_DIR = PROJECT_ROOT / ".opencode"
OPENCODE_TOOLS_DIR = OPENCODE_DIR / "tools"
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# LLM backend — only the API key is external; everything else is local-only.
# ---------------------------------------------------------------------------
SLAC_API_KEY = os.getenv("SLAC_API_KEY", "")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "slac/us.anthropic.claude-opus-4-6-v1")

# opencode runs on this machine, started by us, bound to loopback. No
# auth needed (no remote attacker can reach 127.0.0.1) and the port is
# hardcoded so the FastAPI client always knows where to find it.
OPENCODE_HOST = "127.0.0.1"
OPENCODE_PORT = 4096
OPENCODE_URL = f"http://{OPENCODE_HOST}:{OPENCODE_PORT}"

# `OPENCODE_BIN` is the only env hook left — different dev machines may
# install opencode in different places. Default to the official install
# path; falls back to whatever's on $PATH when launched by start.sh.
OPENCODE_BIN = os.getenv("OPENCODE_BIN", str(Path.home() / ".opencode" / "bin" / "opencode"))

# Long-running tool calls (e.g. a 48-hour run_collection) must not be
# killed by an arbitrary HTTP timeout. Health/session-create still use
# short timeouts inside opencode_client.py.
OPENCODE_MESSAGE_TIMEOUT_S = None  # wait indefinitely

# ---------------------------------------------------------------------------
# Slack — secrets + channel IDs. Empty values disable the bridge.
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
SLACK_LLM_CHANNEL_ID = os.getenv("SLACK_LLM_CHANNEL_ID", "")
SLACK_USERS_CHANNEL_ID = os.getenv("SLACK_USERS_CHANNEL_ID", "")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
# Port 5005 — picked deliberately to avoid the usual collision-magnets
# (5000 is macOS AirPlay; 8080 is everything else).
PORT = 5005
BASE_PATH = ""

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = str(DATA_DIR / "autonomous.db")
os.environ.setdefault("BEAMLINE_DB_PATH", DB_PATH)

# ---------------------------------------------------------------------------
# SPEC dispatcher — defaults to mock so the app boots out-of-box on a
# laptop. Set SPEC_MOCK=0 in .env on the beamline machine.
# ---------------------------------------------------------------------------
SPEC_SCREEN_NAME = "spec"
SPEC_POLL_INTERVAL_S = 2.0
SPEC_PROMPT_REGEX = r"^\d+\.SPEC> ?$"
SPEC_MOCK = os.getenv("SPEC_MOCK", "1") == "1"

# ---------------------------------------------------------------------------
# Orchestrator cadences
# ---------------------------------------------------------------------------
ORCHESTRATOR_ENABLED = True
ORCHESTRATOR_TICK_S = 5.0
STATUS_POST_INTERVAL_S = 900.0
DEFAULT_BEAMTIME_HOURS = 48.0

# Backward phase transitions and human-intervention requests block the
# orchestrator until staff actually responds. There is no timeout — if
# you've decided the agent needs a human, the agent waits for one.

# ---------------------------------------------------------------------------
# EPICS PVs (reference only — not yet wired)
# ---------------------------------------------------------------------------
EPICS_PV_SPEAR_CURRENT = "SPEAR:BeamCurrAvg"
EPICS_PV_BL_STATE = "BL15:State"
EPICS_PV_GAP_OWNER = "BL15:GapOwnerNode"


def llm_enabled() -> bool:
    """True iff the LLM backend is usable (SLAC key present)."""
    return bool(SLAC_API_KEY)
