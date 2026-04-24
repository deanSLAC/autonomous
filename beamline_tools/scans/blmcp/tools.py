"""MCP tool implementations -- thin wrappers around bldata_analysis."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from beamline_tools.scans.bldata_analysis import scans, logs, plotting


# ---- Scan data tools ----

def list_scans(limit=20):
    return scans.list_processed_scans(limit=limit)


def get_latest_scan():
    results = scans.list_processed_scans(limit=1)
    if not results:
        return None
    entry = results[0]
    df = scans.read_processed_scan(entry["file_name"], entry["scan_number"])
    if df is not None:
        entry["data_preview"] = df.head(10).to_string()
        entry["counters"] = list(df.columns)
    return entry


def read_scan(file_name, scan_number):
    meta = scans.get_scan_metadata(file_name, scan_number)
    if not meta:
        return None
    df = scans.read_processed_scan(file_name, scan_number)
    if df is not None:
        meta["data"] = df.to_string()
    return meta


def get_scan_deadtime(file_name, scan_number):
    return scans.get_scan_deadtime(file_name, scan_number)


def get_active_counter(file_name, scan_number):
    return scans.get_active_counter(file_name, scan_number)


# ---- Analysis tools ----

def edge_step_normalize_scan(file_name, scan_number, counter=None, normalize_by="I0"):
    return scans.edge_step_normalize_scan(file_name, scan_number, counter=counter, normalize_by=normalize_by)


def average_energy_scans(file_name=None):
    return scans.average_energy_scans(file_name=file_name)


def average_latest_energy_scans():
    return scans.average_latest_energy_scans()


def analyze_scan_convergence(file_name=None):
    """Analyze scan convergence using cosine similarity metrics."""
    from blmcp.cosine_similarity_tool import analyze_scan_quality

    try:
        combined, file_name, counter, used_scans = scans.get_normalized_scan_arrays(file_name)
    except ValueError as e:
        return {"error": str(e)}

    if len(used_scans) < 2:
        return {"error": f"Need at least 2 scans for convergence analysis, found {len(used_scans)}."}

    scan_data_2d = combined.dropna().values.T.tolist()
    result = analyze_scan_quality(scan_data_2d)

    if "error" in result:
        return result

    result["file_name"] = file_name
    result["active_counter"] = counter
    result["scan_numbers"] = used_scans
    return result


def analyze_scan_efficiency(file_name=None):
    """Comprehensive scan repetition efficiency report."""
    from blmcp.scan_efficiency_tool import analyze_scan_efficiency as _analyze

    try:
        combined, file_name, counter, used_scans = scans.get_normalized_scan_arrays(file_name)
    except ValueError as e:
        return {"error": str(e)}

    if len(used_scans) < 2:
        return {"error": f"Need at least 2 scans for efficiency analysis, found {len(used_scans)}."}

    scan_data_2d = combined.dropna().values.T.tolist()
    result = _analyze(scan_data_2d)

    if "error" in result:
        return result

    result["file_name"] = file_name
    result["active_counter"] = counter
    result["scan_numbers"] = used_scans
    return result


# ---- Log tools ----

def list_logs(limit=20):
    return logs.list_logs(limit=limit)


def get_latest_log_entries(lines=100):
    return logs.get_latest_log_entries(lines=lines)


def search_logs(query, max_results=50):
    return logs.search_logs(query, max_results=max_results)


# ---- Plot tools ----

def plot_scan(file_name, scan_number, counter=None, normalize_by=None):
    """Generate a scan plot for display. Returns (fig, summary) or (None, error)."""
    return plotting.plot_scan(file_name, scan_number, counter=counter, normalize_by=normalize_by)


def plot_averaged_scans_overlay(file_names):
    """Plot averaged energy scans for multiple samples. Returns (fig, summary)."""
    return plotting.plot_averaged_scans_overlay(file_names)


def analyze_scan_plot(file_name, scan_number, counter=None, normalize_by=None):
    """Generate a scan plot for LLM visual analysis. Returns (fig, base64, summary) or (None, None, error)."""
    fig, summary = plotting.plot_scan(file_name, scan_number, counter=counter, normalize_by=normalize_by)
    if fig is None:
        return None, None, summary
    b64 = plotting.fig_to_base64(fig)
    return fig, b64, summary
