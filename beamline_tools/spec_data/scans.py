"""Scan data operations -- reads SPEC files directly via silx.

Uses local_data module for metadata queries and scan reading.
No pickle files required.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from beamline_tools.spec_data import local_data


def list_processed_scans(limit=20):
    """List scans, most recent first."""
    return local_data.list_processed_scans(limit=limit)


def get_scan_metadata(file_name, scan_number):
    """Get full metadata for a single scan."""
    return local_data.get_scan_metadata(file_name, scan_number)


def read_processed_scan(file_name, scan_number):
    """Read scan data from the SPEC file. Returns DataFrame or None."""
    return local_data.read_processed_scan(file_name, scan_number)


def get_scan_deadtime(file_name, scan_number):
    """Get dead time info for a single scan."""
    return local_data.get_scan_deadtime(file_name, scan_number)


def get_active_counter(file_name, scan_number):
    """Determine the 'active' fluorescence/absorption counter for a scan.

    Decision logic:
      1. If 'ppboff' is a counter, it is the active counter.
      2. Else if 'vortDT' is a counter, compare max values of vortDT, vortDT2,
         vortDT3, vortDT4 -- whichever has the highest max is active.
      3. Otherwise, default to 'I1'.
    """
    df = read_processed_scan(file_name, scan_number)
    if df is None:
        return None

    cols = set(df.columns)

    if "ppboff" in cols:
        return {
            "file_name": file_name,
            "scan_number": scan_number,
            "active_counter": "ppboff",
            "reason": "ppboff counter present",
        }

    vort_candidates = ["vortDT", "vortDT2", "vortDT3", "vortDT4"]
    available_vorts = [c for c in vort_candidates if c in cols]
    if available_vorts:
        best = max(available_vorts, key=lambda c: df[c].max())
        return {
            "file_name": file_name,
            "scan_number": scan_number,
            "active_counter": best,
            "reason": f"highest max among {available_vorts}",
        }

    return {
        "file_name": file_name,
        "scan_number": scan_number,
        "active_counter": "I1",
        "reason": "no ppboff or vortDT counters, defaulting to I1",
    }


def _edge_step_normalize(df, counter, normalize_by="I0"):
    """Core edge-step normalization on a scan DataFrame."""
    if counter not in df.columns:
        raise KeyError(f"Counter '{counter}' not found. Available: {list(df.columns)}")
    if normalize_by and normalize_by not in df.columns:
        raise KeyError(f"Normalization counter '{normalize_by}' not found. Available: {list(df.columns)}")

    energy = df.index.values.astype(float)
    signal = df[counter].values.astype(float)

    if normalize_by:
        i0 = df[normalize_by].values.astype(float)
        i0_safe = np.where(i0 == 0, 1.0, i0)
        signal = signal / i0_safe

    n = len(signal)
    n10 = max(1, n // 10)
    pre_mean = np.mean(signal[:n10])
    post_mean = np.mean(signal[-n10:])
    denom = post_mean - pre_mean
    if abs(denom) < 1e-15:
        normalized = signal - pre_mean
    else:
        normalized = (signal - pre_mean) / denom

    return energy, normalized


def edge_step_normalize_scan(file_name, scan_number, counter=None, normalize_by="I0"):
    """Load a scan, normalize by I0, then apply edge-step normalization."""
    df = read_processed_scan(file_name, scan_number)
    if df is None:
        return None

    if counter is None:
        active = get_active_counter(file_name, scan_number)
        if active is None:
            return None
        counter = active["active_counter"]

    try:
        energy, normalized = _edge_step_normalize(df, counter, normalize_by)
    except KeyError as e:
        return {"error": str(e)}

    result_df = pd.DataFrame({"energy": energy, "normalized": normalized})
    result_df = result_df.set_index("energy")

    return {
        "file_name": file_name,
        "scan_number": scan_number,
        "counter": counter,
        "normalize_by": normalize_by,
        "num_points": len(result_df),
        "data": result_df.to_string(),
    }


def get_most_recent_file():
    """Find the most recently modified SPEC file (excluding alignment)."""
    return local_data.get_most_recent_file()


def get_normalized_scan_arrays(file_name=None, e_min=None, e_max=None, scan_numbers=None):
    """Load all scans for a file, normalize, and return as a DataFrame on a common energy grid.

    Parameters
    ----------
    file_name : str, optional
        SPEC file name. If None, uses the most recent file.
    e_min, e_max : float, optional
        If both are given, restrict the returned DataFrame to rows whose energy
        index is in [e_min, e_max]. Edge-step normalization is still performed
        on the full scan (so pre/post anchors are unchanged) — only the
        returned slice is windowed.
    scan_numbers : list[int], optional
        If given, restrict to these specific scan numbers (used by per-spot
        analysis to run the same pipeline on a subset).
    """
    if file_name is None:
        file_name = get_most_recent_file()
        if file_name is None:
            raise ValueError("No SPEC files found.")

    if scan_numbers is None:
        scan_numbers = local_data.get_scan_numbers_for_file(file_name)

    if not scan_numbers:
        raise ValueError(f"No scans found for file '{file_name}'.")

    active = get_active_counter(file_name, scan_numbers[0])
    if active is None:
        raise ValueError(f"Could not load scan data for '{file_name}' scan {scan_numbers[0]}.")
    counter = active["active_counter"]

    normalized_scans = []
    used_scans = []
    for sn in scan_numbers:
        df = read_processed_scan(file_name, sn)
        if df is None:
            continue
        try:
            energy, norm = _edge_step_normalize(df, counter, normalize_by="I0")
        except KeyError:
            continue
        normalized_scans.append(pd.Series(norm, index=energy, name=f"S{sn:03d}"))
        used_scans.append(sn)

    if not normalized_scans:
        raise ValueError(f"No valid scans to normalize in '{file_name}'.")

    combined = pd.concat(normalized_scans, axis=1)

    if e_min is not None and e_max is not None:
        if e_min >= e_max:
            raise ValueError(f"e_min ({e_min}) must be less than e_max ({e_max}).")
        windowed = combined.loc[(combined.index >= e_min) & (combined.index <= e_max)]
        if len(windowed) < 5:
            raise ValueError(
                f"Energy window [{e_min}, {e_max}] yielded only {len(windowed)} points. "
                f"Available range: [{combined.index.min():.2f}, {combined.index.max():.2f}]."
            )
        combined = windowed

    return combined, file_name, counter, used_scans


def _estimate_per_rep_noise(combined: pd.DataFrame, baseline_frac: float = 0.10) -> np.ndarray:
    """Estimate per-rep noise sigma from the standard deviation of the last
    `baseline_frac` of the energy axis (post-edge plateau, defined to be ~1.0
    by edge-step normalization, so any residual std is per-rep noise).

    Returns one sigma per scan column. Falls back to 1.0 (equal-weighted) if
    the baseline window is too short or yields zero std.
    """
    n_points = len(combined)
    n_baseline = max(5, int(n_points * baseline_frac))
    baseline = combined.iloc[-n_baseline:]
    sigmas = baseline.std(axis=0, ddof=1).values
    sigmas = np.where(np.isfinite(sigmas) & (sigmas > 0), sigmas, np.nan)
    if not np.any(np.isfinite(sigmas)):
        return np.ones(combined.shape[1])
    fallback = np.nanmedian(sigmas)
    sigmas = np.where(np.isfinite(sigmas), sigmas, fallback)
    return sigmas


def average_energy_scans(
    file_name=None,
    e_min=None,
    e_max=None,
    weighting: str = "equal",
    scan_numbers=None,
):
    """Average all energy scans in a SPEC file after edge-step normalization.

    Parameters
    ----------
    file_name : str, optional
        SPEC file name. If None, uses the most recent file.
    e_min, e_max : float, optional
        Restrict the returned average to this energy window. Normalization is
        still done on the full scan; only the output is windowed.
    weighting : {"equal", "inverse_variance"}, default "equal"
        "equal": unweighted mean across scans.
        "inverse_variance": weight each scan by 1/sigma_i^2 where sigma_i is
        estimated from the post-edge baseline std of that scan. Higher-SNR
        spots contribute more.
    scan_numbers : list[int], optional
        If given, restrict to these specific scan numbers.
    """
    try:
        combined, file_name, counter, used_scans = get_normalized_scan_arrays(
            file_name, e_min=e_min, e_max=e_max, scan_numbers=scan_numbers
        )
    except ValueError as e:
        return {"error": str(e)}

    if weighting == "inverse_variance":
        # For weighting we need a baseline estimate from the FULL scan, not the
        # windowed slice (the slice may not include the baseline).
        full_combined, _, _, _ = get_normalized_scan_arrays(
            file_name, scan_numbers=scan_numbers
        )
        sigmas = _estimate_per_rep_noise(full_combined)
        weights = 1.0 / np.square(sigmas)
        weights = weights / weights.sum()
        avg = (combined.values * weights[np.newaxis, :]).sum(axis=1)
        # Weighted std across reps (using the same weights, ddof~0)
        diff = combined.values - avg[:, np.newaxis]
        var = (np.square(diff) * weights[np.newaxis, :]).sum(axis=1)
        std = np.sqrt(var)
        avg = pd.Series(avg, index=combined.index)
        std = pd.Series(std, index=combined.index)
        weights_used = weights.tolist()
    elif weighting == "equal":
        avg = combined.mean(axis=1)
        std = combined.std(axis=1)
        weights_used = None
    else:
        return {"error": f"Unknown weighting '{weighting}'. Use 'equal' or 'inverse_variance'."}

    result_df = pd.DataFrame({"energy": avg.index, "average": avg.values, "std": std.values})
    result_df = result_df.set_index("energy")

    out = {
        "file_name": file_name,
        "active_counter": counter,
        "num_scans_averaged": len(used_scans),
        "scan_numbers": used_scans,
        "num_points": len(result_df),
        "weighting": weighting,
        "energy_window": [e_min, e_max] if (e_min is not None and e_max is not None) else None,
        "data": result_df.to_string(),
    }
    if weights_used is not None:
        out["weights_used"] = [round(w, 6) for w in weights_used]
    return out


def average_latest_energy_scans(e_min=None, e_max=None, weighting: str = "equal"):
    """Find the latest file with >1 energy-motor scan and return the average."""
    file_name = local_data.average_latest_energy_scans_file()
    if not file_name:
        return {"error": "No file found with more than 1 energy scan."}
    return average_energy_scans(file_name=file_name, e_min=e_min, e_max=e_max, weighting=weighting)


def group_scans_by_spot(file_name, tol_mm: float = 0.05):
    """Group a file's scans by sample spot, using motor positions (Sx, Sy, Sz).

    Two scans are considered the same spot if their Sx, Sy, Sz all agree within
    `tol_mm`. Returns a list of {"spot_id": int, "center": {Sx,Sy,Sz},
    "scan_numbers": [...]} entries, ordered by first-appearance.

    Reads motor_positions from each scan's df.attrs. Scans missing Sx/Sy/Sz are
    grouped under spot_id=-1 (unknown).
    """
    scan_numbers = local_data.get_scan_numbers_for_file(file_name)
    if not scan_numbers:
        return {"error": f"No scans found for file '{file_name}'."}

    def _motor_xyz(motors: dict) -> tuple[float, float, float] | None:
        """Pull (Sx, Sy, Sz) from motor_positions, tolerating the silx quirk
        where single-space-separated motor names get returned as one joined
        key. We re-split the joined key and pair with the scan's own #P0
        positions stored on disk if needed.
        """
        if not motors:
            return None
        # Direct lookup — works when names parsed correctly.
        try:
            return float(motors["Sx"]), float(motors["Sy"]), float(motors["Sz"])
        except (KeyError, TypeError, ValueError):
            pass
        # Fallback: silx joined the motor names. Each key is a long string;
        # the corresponding value is just the FIRST motor's position. We
        # cannot recover Sx/Sy/Sz from this dict alone — pass through.
        return None

    def _motor_xyz_from_p0(file_name: str, sn: int) -> tuple[float, float, float] | None:
        """Last-resort: parse the #P0 / #O0 lines from the raw SPEC file."""
        from beamline_tools.spec_data import local_data as _ld
        cache = _ld._load_cache()
        entry = cache.get(f"{file_name}::{sn}")
        if not entry or not entry.get("file_path"):
            return None
        try:
            from pathlib import Path as _P
            text = _P(entry["file_path"]).read_text(errors="ignore")
        except OSError:
            return None
        # Find the file-level #O0 (first one) and the per-scan #P0.
        names: list[str] = []
        for line in text.splitlines():
            if line.startswith("#O0 "):
                names = line[4:].split()
                break
        if not names:
            return None
        # Now find the scan's own #P0
        in_scan = False
        for line in text.splitlines():
            if line.startswith(f"#S {sn} "):
                in_scan = True
                continue
            if in_scan and line.startswith("#S "):
                break
            if in_scan and line.startswith("#P0 "):
                try:
                    vals = [float(x) for x in line[4:].split()]
                except ValueError:
                    return None
                idx = {n: i for i, n in enumerate(names)}
                if "Sx" in idx and "Sy" in idx and "Sz" in idx:
                    try:
                        return vals[idx["Sx"]], vals[idx["Sy"]], vals[idx["Sz"]]
                    except IndexError:
                        return None
                return None
        return None

    spots = []  # list of dicts: {"center": (Sx, Sy, Sz), "scan_numbers": [...]}
    unknown = []

    for sn in scan_numbers:
        df = read_processed_scan(file_name, sn)
        if df is None or not hasattr(df, "attrs"):
            unknown.append(sn)
            continue
        motors = df.attrs.get("motor_positions") or {}
        xyz = _motor_xyz(motors) or _motor_xyz_from_p0(file_name, sn)
        if xyz is None:
            unknown.append(sn)
            continue
        sx, sy, sz = xyz

        matched = False
        for spot in spots:
            cx, cy, cz = spot["center"]
            if abs(cx - sx) <= tol_mm and abs(cy - sy) <= tol_mm and abs(cz - sz) <= tol_mm:
                spot["scan_numbers"].append(sn)
                matched = True
                break
        if not matched:
            spots.append({"center": (sx, sy, sz), "scan_numbers": [sn]})

    out = []
    for i, spot in enumerate(spots):
        cx, cy, cz = spot["center"]
        out.append({
            "spot_id": i,
            "center": {"Sx": round(cx, 4), "Sy": round(cy, 4), "Sz": round(cz, 4)},
            "scan_numbers": spot["scan_numbers"],
            "n_scans": len(spot["scan_numbers"]),
        })

    if unknown:
        out.append({"spot_id": -1, "center": None, "scan_numbers": unknown, "n_scans": len(unknown)})

    return {
        "file_name": file_name,
        "tol_mm": tol_mm,
        "n_spots": len([s for s in out if s["spot_id"] != -1]),
        "spots": out,
    }


def get_raw_counter_arrays(file_name=None, scan_numbers=None):
    """Load raw active-counter arrays per scan (NOT normalized), aligned on a
    common energy grid. Used for counts-based Poisson floor calculations.

    Returns (combined_counts_df, file_name, counter, used_scans). The DataFrame
    holds the active counter divided by count time (rate, in counts/sec) so
    different scans with different count times are comparable in shape; total
    counts per point per scan = rate * count_time, exposed in attrs.
    """
    if file_name is None:
        file_name = get_most_recent_file()
        if file_name is None:
            raise ValueError("No SPEC files found.")
    if scan_numbers is None:
        scan_numbers = local_data.get_scan_numbers_for_file(file_name)
    if not scan_numbers:
        raise ValueError(f"No scans found for file '{file_name}'.")

    active = get_active_counter(file_name, scan_numbers[0])
    if active is None:
        raise ValueError(f"Could not load scan data for '{file_name}' scan {scan_numbers[0]}.")
    counter = active["active_counter"]

    series_list = []
    used = []
    count_times = []
    for sn in scan_numbers:
        df = read_processed_scan(file_name, sn)
        if df is None or counter not in df.columns:
            continue
        energy = df.index.values.astype(float)
        ct = df.attrs.get("count_time") or 1.0
        rate = df[counter].values.astype(float) / float(ct)
        series_list.append(pd.Series(rate, index=energy, name=f"S{sn:03d}"))
        used.append(sn)
        count_times.append(float(ct))

    if not series_list:
        raise ValueError(f"No scans with counter '{counter}' found in '{file_name}'.")

    combined = pd.concat(series_list, axis=1)
    combined.attrs["count_times"] = count_times
    combined.attrs["counter"] = counter
    return combined, file_name, counter, used
