"""Configuration for the beamline_tools package.

Owns: SPEC transport, tools-layer SQLite path, reference data paths,
EPICS PV names. Does not know about the LLM, orchestration, or the web
UI — those packages have their own config modules.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
DATA_DIR = PROJECT_ROOT / "data"
OPENCODE_DIR = PROJECT_ROOT / ".opencode"
OPENCODE_TOOLS_DIR = OPENCODE_DIR / "tools"
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# SPEC dispatcher — defaults to mock so the app boots out-of-box on a
# laptop. Set SPEC_MOCK=0 in .env on the beamline machine.
# ---------------------------------------------------------------------------
SPEC_SCREEN_NAME = "spec"
SPEC_POLL_INTERVAL_S = 2.0
SPEC_PROMPT_REGEX = r"^\d+\.SPEC> ?$"
SPEC_MOCK = os.getenv("SPEC_MOCK", "1") == "1"

# Transport for SPEC commands. "tcp" talks the spec server-mode binary
# protocol directly. "screen" falls back to stuffing keystrokes into a
# GNU screen session running spec interactively.
SPEC_TRANSPORT = os.getenv("SPEC_TRANSPORT", "tcp")
SPEC_HOST = os.getenv("SPEC_HOST", "localhost")
SPEC_PORT = int(os.getenv("SPEC_PORT", "2033"))
SPEC_NAME = os.getenv("SPEC_NAME", "spec")

# ---------------------------------------------------------------------------
# Database — action_log + query_log live in their own sqlite file so the
# tools layer carries no schema from the orchestration layer.
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("BEAMLINE_TOOLS_DB_PATH", str(DATA_DIR / "beamline_tools.db"))
os.environ.setdefault("BEAMLINE_TOOLS_DB_PATH", DB_PATH)

# TOOLS_MODE: 'cli' (progressive discovery via beamtimehero --help) or
# 'mcp' (full tool surface in every LLM request). Read by the agent.
TOOLS_MODE = os.getenv("TOOLS_MODE", "cli")

# ---------------------------------------------------------------------------
# EPICS PVs (reference only — not yet wired)
# ---------------------------------------------------------------------------
EPICS_PV_SPEAR_CURRENT = "SPEAR:BeamCurrAvg"
EPICS_PV_BL_STATE = "BL15:State"
EPICS_PV_GAP_OWNER = "BL15:GapOwnerNode"
