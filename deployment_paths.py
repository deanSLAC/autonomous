"""Deployment path bootstrap. Import this FIRST, before anything else.

`beamtimehero_cli.config` reads BEAMTIMEHERO_DATA_DIR at import time and
resolves BEAMTIMEHERO_SAFETY_SWITCHES per call against DATA_DIR. Both must
therefore be set before the first `beamtimehero_cli` import anywhere in the
process, or this repo's writable state lands in the *toolbelt's* checkout.

That is not hypothetical: it is what happened between the SPEC modules moving
upstream and 2026-09-11. The action log — the audit trail for every SPEC
command — wrote to `beamtimehero_cli/data/beamline_tools.db`, and the SPEC
safety switch resolved to a path inside the installed package that does not
exist, where a missing file fails open. The operator's stop switch did nothing.

This module is stdlib-only and imports nothing from this repo on purpose, so
any entry point can import it as its first statement without dragging in a
package `__init__` that would itself reach `beamtimehero_cli` too early.

Every entry point must import it before importing `orchestration`,
`beamline_tools`, `ui` or `beamtimehero_cli`:

    import deployment_paths  # noqa: F401  # must precede every other import

`setdefault`, so an explicit value in the environment still wins.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

DATA_DIR = REPO_ROOT / "data"
SAFETY_SWITCHES = REPO_ROOT / "beamline_tools" / "safety_switches.json"

os.environ.setdefault("BEAMTIMEHERO_DATA_DIR", str(DATA_DIR))
os.environ.setdefault("BEAMTIMEHERO_SAFETY_SWITCHES", str(SAFETY_SWITCHES))

__all__ = ["REPO_ROOT", "DATA_DIR", "SAFETY_SWITCHES"]
