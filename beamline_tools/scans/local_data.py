"""Local filesystem data access -- reads SPEC data files directly via silx.

Scans the active scan directory for SPEC files, parses them with
silx.io.specfile.SpecFile, and caches scan metadata in a JSON sidecar
file for performance on repeated queries.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from silx.io.specfile import SpecFile, is_specfile

logger = logging.getLogger(__name__)

from beamline_tools.scans import bl_config

_metadata_cache: dict | None = None
_cached_file_mtimes: dict[str, float] = {}  # file_path -> mtime at cache time


# ---------------------------------------------------------------------------
# SPEC file helpers
# ---------------------------------------------------------------------------

def _parse_spec_date(header_lines: list[str]) -> str | None:
    """Extract date from #D header line and return as ISO string."""
    for line in header_lines:
        if line.startswith("#D "):
            date_str = line[3:].strip()
            for fmt in (
                "%a %b %d %H:%M:%S %Y",
                "%a %b  %d %H:%M:%S %Y",
            ):
                try:
                    return datetime.strptime(date_str, fmt).isoformat()
                except ValueError:
                    continue
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(date_str).isoformat()
            except Exception:
                pass
    return None


def _parse_count_time(header_lines: list[str]) -> float | None:
    """Extract count time from #T header line."""
    for line in header_lines:
        if line.startswith("#T "):
            parts = line[3:].strip().split()
            if parts:
                try:
                    return float(parts[0])
                except ValueError:
                    pass
    return None


def _parse_scan_command(header_lines: list[str]) -> tuple[int | None, str]:
    """Extract scan number and command from #S header line."""
    for line in header_lines:
        if line.startswith("#S "):
            parts = line[3:].strip().split(None, 1)
            scan_num = int(parts[0]) if parts else None
            command = parts[1] if len(parts) > 1 else ""
            return scan_num, command
    return None, ""


def _read_spec_scan(spec_path: str | Path, scan_index: int) -> pd.DataFrame | None:
    """Read a single scan from a SPEC file and return as a DataFrame."""
    try:
        sf = SpecFile(str(spec_path))
        scan = sf[scan_index]
        labels = scan.labels
        data = scan.data

        if data.size == 0:
            return None

        df = pd.DataFrame(data.T, columns=labels)
        if labels:
            df = df.set_index(labels[0])

        header = scan.scan_header
        date_str = _parse_spec_date(header)
        count_time = _parse_count_time(header)
        _, command = _parse_scan_command(header)

        motor_dict = {}
        try:
            motor_dict = dict(zip(scan.motor_names, scan.motor_positions))
        except Exception:
            pass

        epoch_col = None
        for col in df.columns:
            if col.lower() == "epoch":
                epoch_col = col
                break

        wall_clock = None
        acquisition = None
        dead_time = None
        if count_time is not None:
            acquisition = count_time * len(df)
        if epoch_col is not None and len(df) > 1:
            epoch_vals = df[epoch_col].values.astype(float)
            wall_clock = float(epoch_vals[-1] - epoch_vals[0])
            if acquisition is not None:
                dead_time = wall_clock - acquisition

        df.attrs = {
            "date_time": datetime.fromisoformat(date_str) if date_str else None,
            "epoch": datetime.fromisoformat(date_str).timestamp() if date_str else None,
            "motor_positions": motor_dict,
            "scan_command": command,
            "counters": list(df.columns),
            "num_points": len(df),
            "count_time": count_time,
            "acquisition_seconds": acquisition,
            "wall_clock_seconds": wall_clock,
            "dead_time_seconds": dead_time,
        }
        return df
    except Exception as e:
        logger.debug("Failed to read scan %d from %s: %s", scan_index, spec_path, e)
        return None


# ---------------------------------------------------------------------------
# Scan metadata cache
# ---------------------------------------------------------------------------

def _get_cache_file() -> Path | None:
    scan_dir = bl_config.BL_SCAN_DIR
    if scan_dir:
        return scan_dir / ".scan_metadata_cache.json"
    return None


def _load_cache() -> dict:
    """Load or rebuild the scan metadata cache.

    Checks per-file mtimes to detect new or changed SPEC files and
    re-parses only those files.
    """
    global _metadata_cache, _cached_file_mtimes

    scan_dir = bl_config.BL_SCAN_DIR

    if _metadata_cache is not None:
        # Check if any SPEC files have changed or new ones appeared
        changed = _find_changed_files(scan_dir)
        if not changed:
            return _metadata_cache
        # Re-parse only changed files, merge into existing cache
        logger.info("Re-parsing %d changed SPEC file(s)", len(changed))
        new_entries = _parse_spec_files(changed)
        _metadata_cache.update(new_entries)
        _save_cache()
        return _metadata_cache

    # Try loading from disk
    cache_file = _get_cache_file()
    if cache_file and cache_file.exists():
        try:
            _metadata_cache = json.loads(cache_file.read_text())
            # Rebuild file mtime tracking from cache entries
            for entry in _metadata_cache.values():
                fp = entry.get("file_path")
                if fp:
                    _cached_file_mtimes[fp] = entry.get("file_mtime", 0)
            # Check for changes since disk cache was written
            changed = _find_changed_files(scan_dir)
            if changed:
                logger.info("Re-parsing %d changed SPEC file(s) since last cache", len(changed))
                new_entries = _parse_spec_files(changed)
                _metadata_cache.update(new_entries)
                _save_cache()
            return _metadata_cache
        except (json.JSONDecodeError, OSError):
            pass

    # Build from scratch
    _metadata_cache = _build_metadata_cache()
    _save_cache()
    return _metadata_cache


def _find_changed_files(scan_dir: Path) -> list[Path]:
    """Find SPEC files that are new or have a different mtime than cached."""
    changed = []
    if not scan_dir or not scan_dir.exists():
        return changed

    for child in scan_dir.iterdir():
        if child.is_dir():
            for spec_path in child.iterdir():
                if not spec_path.is_file():
                    continue
                _check_file(spec_path, changed)
        elif child.is_file():
            _check_file(child, changed)

    return changed


def _check_file(spec_path: Path, changed: list[Path]):
    """Check if a single file needs re-parsing."""
    try:
        if not is_specfile(str(spec_path)):
            return
    except Exception:
        return
    fp = str(spec_path)
    current_mtime = spec_path.stat().st_mtime
    if fp not in _cached_file_mtimes or _cached_file_mtimes[fp] < current_mtime:
        changed.append(spec_path)
        _cached_file_mtimes[fp] = current_mtime


def _parse_spec_files(file_list: list[Path]) -> dict:
    """Parse a list of SPEC files and return cache entries."""
    cache = {}
    for spec_path in file_list:
        try:
            sf = SpecFile(str(spec_path))
        except Exception:
            logger.debug("Failed to open SPEC file: %s", spec_path)
            continue

        file_name = spec_path.name
        file_mtime = spec_path.stat().st_mtime
        exp_name = spec_path.parent.name

        for scan_idx in range(len(sf)):
            try:
                scan = sf[scan_idx]
                header = scan.scan_header
                scan_number = scan.number
                _, command = _parse_scan_command(header)
                date_str = _parse_spec_date(header)
                count_time = _parse_count_time(header)
                labels = scan.labels
                data = scan.data
                num_points = data.shape[1] if data.ndim == 2 else 0

                motor_dict = {}
                try:
                    motor_dict = dict(zip(scan.motor_names, scan.motor_positions))
                except Exception:
                    pass

                acquisition = None
                wall_clock = None
                dead_time = None
                if count_time is not None and num_points > 0:
                    acquisition = count_time * num_points
                if num_points > 1 and labels:
                    epoch_idx = None
                    for i, lbl in enumerate(labels):
                        if lbl.lower() == "epoch":
                            epoch_idx = i
                            break
                    if epoch_idx is not None:
                        epoch_vals = data[epoch_idx]
                        wall_clock = float(epoch_vals[-1] - epoch_vals[0])
                        if acquisition is not None:
                            dead_time = wall_clock - acquisition

                key = f"{file_name}::{scan_number}"
                cache[key] = {
                    "file_name": file_name,
                    "file_path": str(spec_path),
                    "experiment": exp_name,
                    "scan_number": scan_number,
                    "scan_index": scan_idx,
                    "scan_command": command,
                    "date_time": date_str,
                    "epoch": datetime.fromisoformat(date_str).timestamp() if date_str else None,
                    "motor_positions": motor_dict,
                    "counters": list(labels) if labels else [],
                    "num_points": num_points,
                    "count_time": count_time,
                    "acquisition_seconds": acquisition,
                    "wall_clock_seconds": wall_clock,
                    "dead_time_seconds": dead_time,
                    "file_mtime": file_mtime,
                }
            except Exception as e:
                logger.debug("Failed to parse scan %d in %s: %s", scan_idx, spec_path, e)
                continue

    return cache


def _build_metadata_cache() -> dict:
    """Scan BL_SCAN_DIR for SPEC files and extract scan metadata via silx."""
    scan_dir = bl_config.BL_SCAN_DIR
    if not scan_dir or not scan_dir.exists():
        return {}

    all_spec_files = []
    for child in scan_dir.iterdir():
        if child.is_dir():
            for spec_path in child.iterdir():
                if spec_path.is_file():
                    try:
                        if is_specfile(str(spec_path)):
                            all_spec_files.append(spec_path)
                            _cached_file_mtimes[str(spec_path)] = spec_path.stat().st_mtime
                    except Exception:
                        continue
        elif child.is_file():
            try:
                if is_specfile(str(child)):
                    all_spec_files.append(child)
                    _cached_file_mtimes[str(child)] = child.stat().st_mtime
            except Exception:
                continue

    return _parse_spec_files(all_spec_files)


def _save_cache():
    """Persist cache to disk."""
    cache_file = _get_cache_file()
    if not cache_file or not _metadata_cache:
        return
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(_metadata_cache, default=str))
    except OSError as e:
        logger.warning("Failed to save metadata cache: %s", e)


def clear_cache():
    """Clear the in-memory cache. Called when scan dir changes."""
    global _metadata_cache, _cached_file_mtimes
    _metadata_cache = None
    _cached_file_mtimes.clear()


def refresh_cache():
    """Force a full cache rebuild."""
    clear_cache()
    _load_cache()


def _all_scans_sorted() -> list[dict]:
    """Return all cached scan metadata, sorted by date_time descending."""
    cache = _load_cache()
    scans = list(cache.values())
    scans.sort(key=lambda s: s.get("date_time") or "", reverse=True)
    return scans


# --- Public API ---

def list_processed_scans(limit=20) -> list[dict]:
    """List scans, most recent first."""
    scans = _all_scans_sorted()[:limit]
    return [
        {
            "file_name": s["file_name"],
            "scan_number": s["scan_number"],
            "scan_command": s["scan_command"],
            "date_time": s["date_time"],
            "num_points": s["num_points"],
            "counters": s["counters"],
            "count_time": s["count_time"],
            "acquisition_seconds": s["acquisition_seconds"],
        }
        for s in scans
    ]


def get_scan_metadata(file_name, scan_number) -> dict | None:
    """Get full metadata for a single scan."""
    cache = _load_cache()
    key = f"{file_name}::{scan_number}"
    entry = cache.get(key)
    if not entry:
        return None
    return {
        "file_name": entry["file_name"],
        "file_path": entry["file_path"],
        "scan_number": entry["scan_number"],
        "scan_command": entry["scan_command"],
        "date_time": entry["date_time"],
        "epoch": entry["epoch"],
        "motor_positions": entry["motor_positions"],
        "counters": entry["counters"],
        "num_points": entry["num_points"],
        "count_time": entry["count_time"],
        "acquisition_seconds": entry["acquisition_seconds"],
    }


def read_processed_scan(file_name, scan_number) -> pd.DataFrame | None:
    """Read scan data from the SPEC file. Returns DataFrame or None."""
    cache = _load_cache()
    key = f"{file_name}::{scan_number}"
    entry = cache.get(key)
    if not entry or not entry.get("file_path"):
        return None
    spec_path = Path(entry["file_path"])
    if not spec_path.exists():
        return None
    scan_index = entry.get("scan_index")
    if scan_index is None:
        return None
    return _read_spec_scan(spec_path, scan_index)


def get_scan_deadtime(file_name, scan_number) -> dict | None:
    """Get dead time info for a single scan."""
    cache = _load_cache()
    key = f"{file_name}::{scan_number}"
    entry = cache.get(key)
    if not entry:
        return None

    acq = entry.get("acquisition_seconds")
    wall = entry.get("wall_clock_seconds")
    dead = entry.get("dead_time_seconds")
    dead_pct = None
    if wall and dead is not None:
        dead_pct = round(100 * dead / wall, 2)

    return {
        "file_name": file_name,
        "scan_number": scan_number,
        "scan_command": entry.get("scan_command"),
        "num_points": entry.get("num_points"),
        "count_time": entry.get("count_time"),
        "acquisition_seconds": acq,
        "wall_clock_seconds": wall,
        "dead_time_seconds": dead,
        "dead_time_pct": dead_pct,
    }


def get_most_recent_file() -> str | None:
    """Find the most recently modified SPEC file (excluding alignment)."""
    for s in _all_scans_sorted():
        if s["file_name"] not in ("alignment", "alignment_Fe"):
            return s["file_name"]
    return None


def average_latest_energy_scans_file() -> str | None:
    """Find latest file with >1 energy scan. Returns file_name or None."""
    cache = _load_cache()

    file_energy_counts: dict[str, tuple[int, str]] = {}
    for entry in cache.values():
        fn = entry["file_name"]
        if fn in ("alignment", "alignment_Fe"):
            continue
        cmd = entry.get("scan_command") or ""
        if cmd.startswith("gscan energy"):
            if fn not in file_energy_counts:
                file_energy_counts[fn] = (0, "")
            count, max_dt = file_energy_counts[fn]
            dt = entry.get("date_time") or ""
            file_energy_counts[fn] = (count + 1, max(max_dt, dt))

    candidates = [(fn, count, max_dt) for fn, (count, max_dt) in file_energy_counts.items() if count > 1]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[0][0]


def get_scan_numbers_for_file(file_name) -> list[int]:
    """Get all scan numbers for a file, sorted ascending."""
    cache = _load_cache()
    numbers = []
    for key, entry in cache.items():
        if entry["file_name"] == file_name:
            numbers.append(entry["scan_number"])
    numbers.sort()
    return numbers


# ---------------------------------------------------------------------------
# File access tools (non-SPEC files in scan dir)
# ---------------------------------------------------------------------------

MAX_READ_SIZE = 100 * 1024  # 100KB


def list_files(pattern: str = "*") -> list[dict]:
    """List non-SPEC files in the scan directory."""
    scan_dir = bl_config.BL_SCAN_DIR
    if not scan_dir or not scan_dir.exists():
        return []

    results = []
    for p in sorted(scan_dir.rglob(pattern)):
        if not p.is_file():
            continue
        # Skip SPEC data files and cache files
        try:
            if is_specfile(str(p)):
                continue
        except Exception:
            pass
        if p.name.startswith("."):
            continue
        results.append({
            "path": str(p.relative_to(scan_dir)),
            "size": p.stat().st_size,
        })
    return results


def read_file(rel_path: str) -> str:
    """Read a file from the scan directory.

    Args:
        rel_path: Path relative to BL_SCAN_DIR.

    Returns:
        File contents as string.

    Raises:
        ValueError: If path is outside scan dir or file too large.
        FileNotFoundError: If file doesn't exist.
    """
    scan_dir = bl_config.BL_SCAN_DIR
    if not scan_dir:
        raise ValueError("No scan directory configured")

    target = (scan_dir / rel_path).resolve()
    # Path traversal check
    try:
        target.relative_to(scan_dir.resolve())
    except ValueError:
        raise ValueError(f"Path is outside scan directory: {rel_path}")

    if not target.is_file():
        raise FileNotFoundError(f"File not found: {rel_path}")

    if target.stat().st_size > MAX_READ_SIZE:
        raise ValueError(f"File too large ({target.stat().st_size} bytes, limit {MAX_READ_SIZE})")

    return target.read_text()


def write_file(filename: str, content: str) -> str:
    """Write a file to the scan directory.

    Args:
        filename: Name only (no subdirectories). Must end in .txt or .mac.
        content: File contents.

    Returns:
        The path of the written file relative to scan dir.

    Raises:
        ValueError: If filename is invalid or path escapes scan dir.
    """
    scan_dir = bl_config.BL_SCAN_DIR
    if not scan_dir:
        raise ValueError("No scan directory configured")

    # Validate extension
    if not (filename.endswith(".txt") or filename.endswith(".mac")):
        raise ValueError("Only .txt and .mac files can be written")

    target = (scan_dir / filename).resolve()
    try:
        target.relative_to(scan_dir.resolve())
    except ValueError:
        raise ValueError(f"Invalid filename: {filename}")

    target.write_text(content)
    return str(target.relative_to(scan_dir))
