"""Autonomy-side configuration: re-exports upstream + adds autonomy-only paths.

Upstream `beamtimehero_cli.config` owns SPEC transport vars, scan/log
directories, sqlite paths, CLI logging knobs, and timezone helpers — values
that are not autonomy-specific. We re-export them verbatim so existing
`from beamline_tools.config import ...` imports continue to work.

Autonomy-only additions:
  * `CONTEXT_DIR`, `PLANS_DIR`, `OPENCODE_DIR`, `OPENCODE_TOOLS_DIR` — paths
    rooted in the autonomous repo (not in `beamtimehero_cli`).
  * `PROJECT_ROOT` is overridden to point at the autonomous repo root.

The autonomous repo's `data/` dir is wired in via `BEAMTIMEHERO_DATA_DIR`
*before* importing upstream config, so upstream's `DATA_DIR` and the
action_log/CLI-log sqlite live next to autonomy's other databases.
"""

from __future__ import annotations

import os
from pathlib import Path

# Resolve the autonomous repo root and force upstream config to use its data/
# dir before upstream's `config.py` runs `Path(os.environ.get(...))`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("BEAMTIMEHERO_DATA_DIR", str(PROJECT_ROOT / "data"))

# Re-export upstream symbols. This must come after the env var override.
from beamtimehero_cli.config import (  # noqa: E402,F401
    BL_LOGS_DIR,
    BL_SCAN_DIR,
    BL_TIMEZONE,
    CLI_LOG_ENABLED,
    CLI_LOG_MAX_RESULT_BYTES,
    DATA_DIR,
    DB_PATH,
    EPICS_PV_BL_STATE,
    EPICS_PV_GAP_OWNER,
    EPICS_PV_SPEAR_CURRENT,
    LOG_FILE_PATTERN,
    MAX_FILE_SIZE_BYTES,
    MAX_LOG_LINES,
    SPEC_EVAL_URL,
    SPEC_HOST,
    SPEC_MOCK,
    SPEC_NAME,
    SPEC_POLL_INTERVAL_S,
    SPEC_PORT,
    SPEC_PROMPT_REGEX,
    SPEC_SCREEN_NAME,
    SPEC_TRANSPORT,
    TOOLS_MODE,
    now_pacific,
    set_scan_dir,
)

# ---------------------------------------------------------------------------
# Autonomy-only paths
# ---------------------------------------------------------------------------
CONTEXT_DIR = PROJECT_ROOT / "context"
PLANS_DIR = PROJECT_ROOT / "logs" / "plans"
OPENCODE_DIR = PROJECT_ROOT / ".opencode"
OPENCODE_TOOLS_DIR = OPENCODE_DIR / "tools"
PLANS_DIR.mkdir(parents=True, exist_ok=True)
