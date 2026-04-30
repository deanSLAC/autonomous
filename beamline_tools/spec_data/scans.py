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


def get_normalized_scan_arrays(file_name=None):
    """Load all scans for a file, normalize, and return as a DataFrame on a common energy grid."""
    if file_name is None:
        file_name = get_most_recent_file()
        if file_name is None:
            raise ValueError("No SPEC files found.")

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
    return combined, file_name, counter, used_scans


def average_energy_scans(file_name=None):
    """Average all energy scans in a SPEC file after edge-step normalization."""
    try:
        combined, file_name, counter, used_scans = get_normalized_scan_arrays(file_name)
    except ValueError as e:
        return {"error": str(e)}

    avg = combined.mean(axis=1)
    std = combined.std(axis=1)

    result_df = pd.DataFrame({"energy": avg.index, "average": avg.values, "std": std.values})
    result_df = result_df.set_index("energy")

    return {
        "file_name": file_name,
        "active_counter": counter,
        "num_scans_averaged": len(used_scans),
        "scan_numbers": used_scans,
        "num_points": len(result_df),
        "data": result_df.to_string(),
    }


def average_latest_energy_scans():
    """Find the latest file with >1 energy-motor scan and return the average."""
    file_name = local_data.average_latest_energy_scans_file()
    if not file_name:
        return {"error": "No file found with more than 1 energy scan."}
    return average_energy_scans(file_name=file_name)
