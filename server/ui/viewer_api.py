"""Data viewer API — enumerates SPEC files for a holder and serves
parsed scan data for plotting in the /viewer page.

Mirrors the capabilities of playground/src/data_viewer.py (which is a
Streamlit app) but returns JSON so the BL15-2 plain-JS frontend can
render the plots with uPlot/plain canvas.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException

from db.client import get_experiment, get_samples_for_holder, get_session
from db.models import SampleHolder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/viewer", tags=["viewer"])


def _resolve_scan_dirs(experiment_id: Optional[str]) -> list[Path]:
    """Find the directories we should look in for scan files.

    Preference order:
      1. Experiment.data_path, if it exists on disk.
      2. $BL_SCAN_DIR (/ simulation) top-level.
      3. Any immediate subdirectory of BL_SCAN_DIR whose name matches
         the experiment name (best-effort).
      4. Every non-hidden immediate subdirectory of the chosen roots
         — covers the common pattern where scans live in
         BL_SCAN_DIR/<experiment-name>/.
    """
    import os
    candidates: list[Path] = []
    if experiment_id:
        exp = get_experiment(experiment_id)
        if exp and exp.data_path:
            p = Path(exp.data_path)
            if p.exists():
                candidates.append(p)
    scan_root = os.environ.get("BL_SCAN_DIR") or ""
    if scan_root:
        root = Path(scan_root)
        if root.exists():
            candidates.append(root)
            if experiment_id:
                exp = get_experiment(experiment_id)
                if exp and exp.name:
                    guess = root / exp.name
                    if guess.exists():
                        candidates.append(guess)
    # Also include non-hidden immediate subdirectories of every candidate
    expanded: list[Path] = []
    for c in list(candidates):
        expanded.append(c)
        try:
            for sub in c.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    expanded.append(sub)
        except OSError:
            pass
    # Dedup while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for c in expanded:
        try:
            key = str(c.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _list_spec_files(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    try:
        from silx.io.specfile import is_specfile
    except ImportError:
        is_specfile = None

    out: list[dict] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name.startswith("log_"):
            continue
        if is_specfile is not None:
            try:
                if not is_specfile(str(p)):
                    continue
            except Exception:
                continue
        try:
            mtime = p.stat().st_mtime
            size = p.stat().st_size
        except OSError:
            continue
        out.append({
            "path": str(p),
            "name": p.name,
            "size": size,
            "mtime": mtime,
        })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


@router.get("/files")
def files(
    experiment_id: Optional[str] = None,
    holder_id: Optional[str] = None,
):
    """List SPEC files relevant to an experiment (and optionally a holder).

    Holder filtering is a convenience: if the sample names from the
    holder appear anywhere in the file name, that file is prioritized.
    (SPEC files are typically named per-sample by `newfile`.)
    """
    if holder_id and not experiment_id:
        with get_session() as session:
            h = session.get(SampleHolder, holder_id)
        if h is None:
            raise HTTPException(404, "sample holder not found")
        experiment_id = h.experiment_id

    dirs = _resolve_scan_dirs(experiment_id)
    files_all: list[dict] = []
    for d in dirs:
        for f in _list_spec_files(d):
            f["directory"] = str(d)
            files_all.append(f)

    holder_name = None
    sample_names: list[str] = []
    if holder_id:
        with get_session() as session:
            h = session.get(SampleHolder, holder_id)
        if h is not None:
            holder_name = h.name
            sample_names = [s.sample_name for s in get_samples_for_holder(holder_id)]

    # Flag files likely associated with the holder (name match on any sample)
    for f in files_all:
        base = Path(f["name"]).stem
        match = None
        lowered = f["name"].lower()
        if holder_name and holder_name.lower() in lowered:
            match = holder_name
        for sn in sample_names:
            if sn and sn.lower() in lowered:
                match = sn
                break
        f["holder_match"] = match
        f["stem"] = base

    files_all.sort(key=lambda x: (0 if x.get("holder_match") else 1, -x["mtime"]))
    return {
        "experiment_id": experiment_id,
        "holder_id": holder_id,
        "holder_name": holder_name,
        "sample_names": sample_names,
        "directories": [str(d) for d in dirs],
        "files": files_all,
    }


def _list_scans_in_file(path: str) -> list[dict]:
    from spec_reader import list_scans
    rows = list_scans(path)
    return rows


@router.get("/scans")
def scans(path: str):
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "file not found")
    try:
        return {"path": str(p), "scans": _list_scans_in_file(str(p))}
    except Exception as e:
        raise HTTPException(500, f"failed to read SPEC file: {e}")


@router.get("/scan_data")
def scan_data(path: str, scan: int):
    from spec_reader import get_scan_data, parse_scan_command
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "file not found")
    try:
        result = get_scan_data(str(p), scan)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"failed to read scan: {e}")

    columns = result.get("columns", []) or []
    data = {k: _arr_to_list(v) for k, v in (result.get("data") or {}).items()}
    parsed = parse_scan_command(result.get("command", ""))
    return {
        "path": str(p),
        "scan": scan,
        "command": result.get("command"),
        "columns": columns,
        "data": data,
        "motor_positions": result.get("motor_positions", {}),
        "scanned_motor": result.get("scanned_motor") or parsed.get("motor") or "",
        "n_points": result.get("n_points"),
    }


def _arr_to_list(a: Any) -> list:
    if isinstance(a, np.ndarray):
        return a.astype(float).tolist()
    try:
        return list(a)
    except TypeError:
        return []
