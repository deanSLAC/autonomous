"""Shared configuration for BL15-2 beamline tools."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BL_TIMEZONE = ZoneInfo("America/Los_Angeles")


def now_pacific() -> datetime:
    """Return current time in Pacific, as a naive datetime for comparison."""
    return datetime.now(BL_TIMEZONE).replace(tzinfo=None)


# Data directories
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


# Mutable scan directory — set at startup, changeable via !setdir
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


# File patterns
LOG_FILE_PATTERN = "log__*"

# Limits
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_LOG_LINES = 1000
