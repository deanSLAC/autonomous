"""Configuration for the orchestration package.

Owns: LLM backend (opencode URL, API key, model), orchestrator cadences,
orchestration-layer SQLite path. The UI reads none of this directly —
it goes through orchestration.api.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths (shared layout lives at the repo root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# LLM backend — only the API key is external; everything else is local-only.
# ---------------------------------------------------------------------------
SLAC_API_KEY = os.getenv("SLAC_API_KEY", "")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "slac/us.anthropic.claude-opus-4-6-v1")

# opencode runs on this machine, started by us, bound to loopback.
OPENCODE_HOST = "127.0.0.1"
OPENCODE_PORT = 4096
OPENCODE_URL = f"http://{OPENCODE_HOST}:{OPENCODE_PORT}"

OPENCODE_BIN = os.getenv("OPENCODE_BIN", str(Path.home() / ".opencode" / "bin" / "opencode"))

# Long-running tool calls (e.g. a 48-hour run_collection) must not be
# killed by an arbitrary HTTP timeout. Health/session-create still use
# short timeouts inside opencode_client.py.
OPENCODE_MESSAGE_TIMEOUT_S = None

# ---------------------------------------------------------------------------
# Orchestrator cadences
# ---------------------------------------------------------------------------
ORCHESTRATOR_ENABLED = True
ORCHESTRATOR_TICK_S = 5.0
STATUS_POST_INTERVAL_S = 900.0
DEFAULT_BEAMTIME_HOURS = 48.0

# ---------------------------------------------------------------------------
# Database — plan, phase, intervention, staff_guidance, sample tables.
# Separate sqlite file from beamline_tools so the two layers can live in
# different projects.
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("ORCHESTRATION_DB_PATH", str(DATA_DIR / "orchestration.db"))
os.environ.setdefault("ORCHESTRATION_DB_PATH", DB_PATH)


def llm_enabled() -> bool:
    """True iff the LLM backend is usable (SLAC key present)."""
    return bool(SLAC_API_KEY)
