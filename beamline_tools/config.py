"""Configuration for the beamline_tools package.

Owns: SPEC transport, tools-layer SQLite path, reference data paths,
EPICS PV names, beamline scan/log directories, timezone. Does not know
about the LLM, orchestration, or the web UI — those packages have their
own config modules.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Beamline data directories (scan files, control logs) and timezone
# ---------------------------------------------------------------------------
BL_TIMEZONE = ZoneInfo("America/Los_Angeles")


def now_pacific() -> datetime:
    """Return current time in Pacific, as a naive datetime for comparison."""
    return datetime.now(BL_TIMEZONE).replace(tzinfo=None)


BL_LOGS_DIR = Path(os.getenv("BL_LOGS_DIR", "/usr/local/lib/spec.log/logfiles"))
if not BL_LOGS_DIR.exists():
    BL_LOGS_DIR = Path(__file__).parent / "sample_data"

_DATA_ROOT = Path(os.getenv("BL_SCAN_DIR", "/data/fifteen"))


def _resolve_scan_dir(root: Path) -> Path:
    """Pick the most recently modified YYYY-mm_* subdirectory, or fall back."""
    if root.is_dir():
        subdirs = [d for d in root.iterdir()
                    if d.is_dir() and re.match(r"\d{4}-\d{2}_", d.name)]
        if subdirs:
            return max(subdirs, key=lambda d: d.stat().st_mtime)
    return Path(__file__).parent / "sample_data"


BL_SCAN_DIR = _resolve_scan_dir(_DATA_ROOT)


def set_scan_dir(name: str) -> Path:
    """Set BL_SCAN_DIR to a subdirectory of _DATA_ROOT.

    Args:
        name: Either a directory name (e.g. '2026-04_Username') or 'auto'
              to re-run auto-detect.

    Returns:
        The new BL_SCAN_DIR path.

    Raises:
        ValueError: If the directory doesn't exist.
    """
    global BL_SCAN_DIR

    if name == "auto":
        BL_SCAN_DIR = _resolve_scan_dir(_DATA_ROOT)
        logger.info("Scan directory auto-detected: %s", BL_SCAN_DIR)
        return BL_SCAN_DIR

    target = _DATA_ROOT / name
    if not target.is_dir():
        raise ValueError(f"Directory does not exist: {target}")

    BL_SCAN_DIR = target
    logger.info("Scan directory set to: %s", BL_SCAN_DIR)
    return BL_SCAN_DIR


LOG_FILE_PATTERN = "log__*"

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_LOG_LINES = 1000
