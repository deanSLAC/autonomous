"""Simulation mode bootstrap.

When `SIMULATION_MODE=1` is set in the environment, calling
`bootstrap()` early in the FastAPI startup path will:

  1. Force `SPEC_MOCK=1` so `screen_client` short-circuits to the
     in-memory simulator.
  2. Point `BL_SCAN_DIR` and `BL_LOGS_DIR` at the bundled mock
     fixtures under `simulation/data` and `simulation/logs`.
  3. Seed those directories with a couple of pre-existing scans so
     the agent's first call to `get_latest_scan` returns something.

Order matters — `bl_config` reads `BL_SCAN_DIR` at import time, so
`bootstrap()` MUST run before anything imports `bl_config`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import engine, fixtures

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"


def is_enabled() -> bool:
    return os.getenv("SIMULATION_MODE", "0") == "1"


def bootstrap(force: bool = False) -> dict:
    if not (force or is_enabled()):
        return {"enabled": False}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    os.environ["SPEC_MOCK"] = "1"
    os.environ["BL_SCAN_DIR"] = str(DATA_DIR)
    os.environ["BL_LOGS_DIR"] = str(LOGS_DIR)

    info = fixtures.seed(DATA_DIR, LOGS_DIR)
    logger.info("simulation bootstrap: scan_dir=%s logs_dir=%s files=%s",
                info["scan_dir"], info["logs_dir"], info["files"])
    return {"enabled": True, **info}


def status() -> dict:
    return {"enabled": is_enabled(), **engine.status()}
