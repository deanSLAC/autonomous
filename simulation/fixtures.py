"""Idempotent seeding of mock SPEC + log fixtures."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import engine


def seed(scan_dir: Path, logs_dir: Path) -> dict:
    """Create mock fixture files if they don't already exist.

    Layout (under `scan_dir`):
        2026-04_simulation/mock.alignment   3 short alignment scans
        2026-04_simulation/mock.01          2 Fe K-edge XAS scans
    The dated subdir is required by `bl_config._resolve_scan_dir`
    which only picks `YYYY-mm_*` directories.
    """
    scan_dir = Path(scan_dir)
    logs_dir = Path(logs_dir)
    scan_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    exp_dir = scan_dir / "2026-04_simulation"
    exp_dir.mkdir(parents=True, exist_ok=True)

    engine.configure(scan_dir=exp_dir, default_file="mock.01")

    align_path = exp_dir / "mock.alignment"
    if not align_path.exists():
        engine.set_current_file("mock.alignment")
        engine.append_ascan("m1vert", 1.7, 2.1, 41, 0.5)
        engine.append_ascan("m2horz", -0.2, 0.4, 31, 0.5)
        engine.append_ascan("pitcha", -0.05, 0.05, 21, 0.5)

    main_path = exp_dir / "mock.01"
    if not main_path.exists():
        engine.set_current_file("mock.01")
        engine.append_xas_scan("Fe", count_time=0.5, n_points=101)
        engine.append_xas_scan("Fe", count_time=0.5, n_points=101)

    engine.set_current_file("mock.01")

    log_path = logs_dir / "log__simulation"
    if not log_path.exists():
        ts = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
        lines = [
            f"### {ts} ### startup of beamline mock session",
            f"### {ts} ### beam: SPEAR=485 mA, BL=OPEN, gap_owned=1",
            f"### {ts} ### loaded sample holder MOCK-1",
            f"### {ts} ### Fe K-edge alignment complete",
        ]
        log_path.write_text("\n".join(lines) + "\n")

    return {
        "scan_dir": str(exp_dir),
        "logs_dir": str(logs_dir),
        "files": [p.name for p in exp_dir.iterdir() if p.is_file()],
    }
