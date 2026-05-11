"""
reports.py

Report generation for BL15-2 beamline automation.
Generates PNG summary images for alignment phases, spectrometer alignment,
sample alignment, and collection progress. Images are posted to Slack
and stored in the database.

All scan data is read via spec_reader (silx-based).
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path
from datetime import datetime
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from beamline_tools.spec_data.spec_reader import get_scan_data, get_scan_xy, parse_scan_command

logger = logging.getLogger(__name__)

# Preferred matplotlib style — fall back gracefully
try:
    plt.style.use("seaborn-v0_8-whitegrid")
except OSError:
    try:
        plt.style.use("seaborn-whitegrid")
    except OSError:
        pass  # use default

# Grid layout labels for alignment_report 2x4
ALIGNMENT_GRID_LABELS = [
    "monvtra", "monhtra", "m1vert", "m2horz",
    "pitch",   "monvgap", "Bz",     "Bx",
]


def _ensure_output_dir(output_dir: str) -> Path:
    """Create output directory if it does not exist. Returns Path."""
    p = Path(output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _timestamp_str() -> str:
    """Return a filesystem-safe timestamp string."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _compute_scan_stats(x: np.ndarray, y: np.ndarray) -> dict:
    """Compute basic statistics for a 1D scan.

    Returns dict with peak_x, peak_y, centroid, fwhm (or None for each
    if not computable).
    """
    stats = {"peak_x": None, "peak_y": None, "centroid": None, "fwhm": None}
    if x.size == 0 or y.size == 0:
        return stats

    peak_idx = int(np.argmax(y))
    stats["peak_x"] = float(x[peak_idx])
    stats["peak_y"] = float(y[peak_idx])

    # Centroid (baseline-shifted)
    y_shifted = y - y.min()
    total = y_shifted.sum()
    if total > 0:
        stats["centroid"] = float(np.sum(x * y_shifted) / total)

    # FWHM estimate from half-max crossings
    half_max = y_shifted.max() / 2.0
    if half_max > 0:
        above = y_shifted >= half_max
        if above.any():
            indices = np.where(above)[0]
            stats["fwhm"] = float(x[indices[-1]] - x[indices[0]])

    return stats


def _plot_scan_subplot(ax, spec_datafile: str, scan_number: int, label: str):
    """Plot a single scan into an axes, with peak marker and stats annotation.

    If scan data cannot be loaded, shows a 'No data' placeholder.
    """
    try:
        x, y = get_scan_xy(spec_datafile, scan_number)
        scan_data = get_scan_data(spec_datafile, scan_number)
        command = scan_data.get("command", "")
        parsed = parse_scan_command(command)
        motor = parsed.get("motor", label)

        ax.scatter(x, y, s=6, alpha=0.7, color="#1f77b4", zorder=2)
        ax.plot(x, y, linewidth=0.8, alpha=0.5, color="#1f77b4", zorder=1)

        stats = _compute_scan_stats(x, y)

        # Mark peak position
        if stats["peak_x"] is not None:
            ax.axvline(stats["peak_x"], color="#d62728", linewidth=0.8,
                       linestyle="--", alpha=0.6, label="peak")

        # Mark centroid if different enough from peak
        if (stats["centroid"] is not None and stats["peak_x"] is not None
                and abs(stats["centroid"] - stats["peak_x"]) > (x.max() - x.min()) * 0.01):
            ax.axvline(stats["centroid"], color="#2ca02c", linewidth=0.8,
                       linestyle=":", alpha=0.6, label="centroid")

        # Annotation text
        ann_parts = [f"#{scan_number}"]
        if stats["peak_x"] is not None:
            ann_parts.append(f"pk={stats['peak_x']:.4f}")
        if stats["fwhm"] is not None:
            ann_parts.append(f"fw={stats['fwhm']:.4f}")
        ax.text(0.02, 0.96, "\n".join(ann_parts),
                transform=ax.transAxes, fontsize=6, va="top",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8))

        ax.set_xlabel(motor, fontsize=7)
        ax.set_title(label, fontsize=8, fontweight="bold")
        ax.tick_params(labelsize=6)

    except Exception as exc:
        logger.warning("Could not plot scan #%d for '%s': %s", scan_number, label, exc)
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="#999999")
        ax.set_title(label, fontsize=8, fontweight="bold")
        ax.tick_params(labelsize=6)


def alignment_report(
    spec_datafile: str,
    scan_numbers: list[int],
    output_dir: str = "/tmp/beamline_reports",
    metadata: dict = None,
) -> str:
    """Generate a 3x3 grid summary of beamline alignment scans.

    Grid layout:
      [monvtra scan] [monhtra scan] [m1vert scan]  [m2horz scan]
      [pitch scan]   [monvgap scan] [Bz scan]      [Bx scan]

    Each subplot shows a scatter plot of motor position vs signal intensity,
    with peak/centroid marked and basic statistics annotated.

    A bottom annotation bar shows energy, crystal, beam FWHM, anomaly flags,
    and timestamp.

    Args:
        spec_datafile: Path to SPEC data file.
        scan_numbers: List of up to 8 scan numbers corresponding to the grid
            positions. If fewer than 8, remaining slots show 'No data'.
        output_dir: Directory to save the output PNG.
        metadata: Optional dict with keys: energy, crystal, beam_h_fwhm,
            beam_v_fwhm, anomaly_flags, timestamp, experiment_name.

    Returns:
        Absolute path to the saved PNG file.
    """
    if metadata is None:
        metadata = {}

    out_path = _ensure_output_dir(output_dir)

    fig = plt.figure(figsize=(12, 6), dpi=150)

    # Use gridspec to leave room for annotation bar at bottom
    gs = gridspec.GridSpec(3, 4, figure=fig, height_ratios=[1, 1, 0.16],
                           hspace=0.45, wspace=0.35)

    # Pad scan_numbers to length 8
    padded_scans = list(scan_numbers) + [None] * (8 - len(scan_numbers))

    for idx in range(8):
        row, col = divmod(idx, 4)
        ax = fig.add_subplot(gs[row, col])
        label = ALIGNMENT_GRID_LABELS[idx] if idx < len(ALIGNMENT_GRID_LABELS) else f"slot {idx}"

        if padded_scans[idx] is not None:
            _plot_scan_subplot(ax, spec_datafile, padded_scans[idx], label)
        else:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10, color="#999999")
            ax.set_title(label, fontsize=8, fontweight="bold")
            ax.tick_params(labelsize=6)

    # Bottom annotation bar
    ax_ann = fig.add_subplot(gs[2, :])
    ax_ann.axis("off")

    ann_parts = []
    if "experiment_name" in metadata:
        ann_parts.append(f"Experiment: {metadata['experiment_name']}")
    if "energy" in metadata:
        ann_parts.append(f"Energy: {metadata['energy']:.1f} eV")
    if "crystal" in metadata:
        ann_parts.append(f"Crystal: {metadata['crystal']}")
    if "beam_h_fwhm" in metadata:
        ann_parts.append(f"Beam H: {metadata['beam_h_fwhm']:.1f} um")
    if "beam_v_fwhm" in metadata:
        ann_parts.append(f"Beam V: {metadata['beam_v_fwhm']:.1f} um")
    if "anomaly_flags" in metadata and metadata["anomaly_flags"]:
        flags = metadata["anomaly_flags"]
        if isinstance(flags, list):
            flags = ", ".join(flags)
        ann_parts.append(f"ANOMALIES: {flags}")

    ts = metadata.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ann_parts.append(str(ts))

    ax_ann.text(0.5, 0.5, "  |  ".join(ann_parts),
                transform=ax_ann.transAxes, ha="center", va="center",
                fontsize=7, color="#333333",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#f0f0f0", alpha=0.9))

    filename = f"alignment_report_{_timestamp_str()}.png"
    filepath = str(out_path / filename)
    fig.savefig(filepath, bbox_inches="tight", dpi=150)
    plt.close(fig)

    logger.info("Alignment report saved to %s", filepath)
    return filepath


def spectrometer_report(
    spec_datafile: str,
    scan_numbers: list[int],
    elements: list[dict] = None,
    output_dir: str = "/tmp/beamline_reports",
) -> str:
    """Generate spectrometer (XES) alignment summary.

    Layout:
    - Top row: per-crystal c#y (pitch) scans overlaid
    - Middle row: per-crystal c#p (roll) scans overlaid
    - Bottom: resolution table as text annotation

    Scans are classified by motor name (c#y = pitch, c#p = roll) parsed
    from the scan command. Scans that do not match either pattern are
    placed in whichever category has fewer entries.

    Args:
        spec_datafile: Path to SPEC data file.
        scan_numbers: List of scan numbers from the xes_align run.
        elements: Optional list of dicts with keys: symbol, crystal_cut,
            expected_fwhm. Used in the resolution table.
        output_dir: Directory to save the output PNG.

    Returns:
        Absolute path to the saved PNG file.
    """
    if elements is None:
        elements = []

    out_path = _ensure_output_dir(output_dir)

    # Classify scans into pitch (c#y) and roll (c#p) categories
    pitch_scans = []  # (scan_number, crystal_id, scan_data)
    roll_scans = []
    other_scans = []

    for sn in scan_numbers:
        try:
            sd = get_scan_data(spec_datafile, sn)
            motor = sd.get("scanned_motor", "")
            command = sd.get("command", "")

            # c1y..c7y = pitch (Ath), c1p..c7p = roll (Achi)
            if len(motor) >= 2 and motor[0] == "c" and motor[-1] == "y":
                crystal_id = motor[1:-1]
                pitch_scans.append((sn, crystal_id, sd))
            elif len(motor) >= 2 and motor[0] == "c" and motor[-1] == "p":
                crystal_id = motor[1:-1]
                roll_scans.append((sn, crystal_id, sd))
            elif "emiss" in motor or "mono" in motor or "energy" in motor:
                other_scans.append((sn, motor, sd))
            else:
                other_scans.append((sn, motor, sd))
        except Exception as exc:
            logger.warning("Could not read scan #%d: %s", sn, exc)

    fig = plt.figure(figsize=(10, 8), dpi=150)
    gs = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[1, 1, 0.4],
                           hspace=0.35)

    colors = plt.cm.tab10(np.linspace(0, 1, 10))

    # --- Top: Pitch scans overlaid ---
    ax_pitch = fig.add_subplot(gs[0])
    if pitch_scans:
        for i, (sn, cid, sd) in enumerate(pitch_scans):
            try:
                x, y = get_scan_xy(spec_datafile, sn)
                # Normalize for overlay
                y_norm = (y - y.min()) / (y.max() - y.min() + 1e-10)
                color = colors[i % len(colors)]
                ax_pitch.plot(x, y_norm, linewidth=1.2, alpha=0.8,
                              color=color, label=f"c{cid}y #{sn}")
                ax_pitch.scatter(x, y_norm, s=4, alpha=0.5, color=color)
            except Exception:
                pass
        ax_pitch.legend(fontsize=6, ncol=4, loc="upper right")
    else:
        ax_pitch.text(0.5, 0.5, "No pitch scans", transform=ax_pitch.transAxes,
                      ha="center", va="center", fontsize=10, color="#999999")
    ax_pitch.set_title("Crystal Pitch (c#y) Scans", fontsize=9, fontweight="bold")
    ax_pitch.set_xlabel("Ath (deg)", fontsize=7)
    ax_pitch.set_ylabel("Normalized intensity", fontsize=7)
    ax_pitch.tick_params(labelsize=6)

    # --- Middle: Roll scans overlaid ---
    ax_roll = fig.add_subplot(gs[1])
    if roll_scans:
        for i, (sn, cid, sd) in enumerate(roll_scans):
            try:
                x, y = get_scan_xy(spec_datafile, sn)
                y_norm = (y - y.min()) / (y.max() - y.min() + 1e-10)
                color = colors[i % len(colors)]
                ax_roll.plot(x, y_norm, linewidth=1.2, alpha=0.8,
                             color=color, label=f"c{cid}p #{sn}")
                ax_roll.scatter(x, y_norm, s=4, alpha=0.5, color=color)
            except Exception:
                pass
        ax_roll.legend(fontsize=6, ncol=4, loc="upper right")
    else:
        ax_roll.text(0.5, 0.5, "No roll scans", transform=ax_roll.transAxes,
                     ha="center", va="center", fontsize=10, color="#999999")
    ax_roll.set_title("Crystal Roll (c#p) Scans", fontsize=9, fontweight="bold")
    ax_roll.set_xlabel("Achi (deg)", fontsize=7)
    ax_roll.set_ylabel("Normalized intensity", fontsize=7)
    ax_roll.tick_params(labelsize=6)

    # --- Bottom: Resolution table ---
    ax_table = fig.add_subplot(gs[2])
    ax_table.axis("off")

    # Build resolution table from scan statistics
    table_rows = []
    header = ["Crystal", "Motor", "Scan #", "Peak Pos", "FWHM", "Peak Cts"]

    all_classified = pitch_scans + roll_scans
    for sn, cid, sd in all_classified:
        try:
            x, y = get_scan_xy(spec_datafile, sn)
            stats = _compute_scan_stats(x, y)
            motor = sd.get("scanned_motor", "?")
            table_rows.append([
                f"c{cid}", motor, str(sn),
                f"{stats['peak_x']:.4f}" if stats["peak_x"] is not None else "---",
                f"{stats['fwhm']:.4f}" if stats["fwhm"] is not None else "---",
                f"{stats['peak_y']:.0f}" if stats["peak_y"] is not None else "---",
            ])
        except Exception:
            table_rows.append([f"c{cid}", "?", str(sn), "---", "---", "---"])

    if table_rows:
        table = ax_table.table(
            cellText=table_rows, colLabels=header,
            cellLoc="center", loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(6)
        table.scale(1.0, 1.1)
        # Style header
        for j in range(len(header)):
            table[0, j].set_facecolor("#d0d0d0")
            table[0, j].set_text_props(fontweight="bold")
    else:
        ax_table.text(0.5, 0.5, "No resolution data available",
                      transform=ax_table.transAxes, ha="center", va="center",
                      fontsize=8, color="#999999")

    # Add element info if provided
    if elements:
        elem_text = "  |  ".join(
            f"{e.get('symbol', '?')} {e.get('crystal_cut', '')}"
            + (f" (exp FWHM: {e['expected_fwhm']:.2f})" if "expected_fwhm" in e else "")
            for e in elements
        )
        fig.text(0.5, 0.01, elem_text, ha="center", fontsize=6, color="#555555")

    filename = f"spectrometer_report_{_timestamp_str()}.png"
    filepath = str(out_path / filename)
    fig.savefig(filepath, bbox_inches="tight", dpi=150)
    plt.close(fig)

    logger.info("Spectrometer report saved to %s", filepath)
    return filepath


def sample_report(
    spec_datafile: str,
    survey_scan: int,
    sample_scans: dict = None,
    sample_positions: list[dict] = None,
    output_dir: str = "/tmp/beamline_reports",
) -> str:
    """Generate sample alignment summary.

    Layout:
    - Top: wide Sz survey with detected peak positions marked
    - Bottom grid: per-sample fine alignment plots (Sz, Sx/Sy boundaries)
    - Table: sample | SX range | SY range | SZ range | spots | emiss eV

    Args:
        spec_datafile: Path to SPEC data file.
        survey_scan: Scan number for the wide Sz survey.
        sample_scans: Dict mapping sample number (int) to list of scan numbers
            for that sample's fine alignment. E.g. {1: [15, 16, 17], 2: [18, 19, 20]}
        sample_positions: List of SamplePosition-like dicts with keys:
            sample_number, sample_name, element_symbol, sx_lo, sx_hi,
            sy_lo, sy_hi, sz_lo, sz_hi, total_spots, emiss_energy_eV.
        output_dir: Directory to save the output PNG.

    Returns:
        Absolute path to the saved PNG file.
    """
    if sample_scans is None:
        sample_scans = {}
    if sample_positions is None:
        sample_positions = []

    out_path = _ensure_output_dir(output_dir)
    n_samples = max(len(sample_scans), len(sample_positions), 1)

    # Figure layout: survey on top, then sample grid, then table
    n_sample_rows = max(1, (n_samples + 2) // 3)
    height_ratios = [1.2] + [0.8] * n_sample_rows + [0.3]
    total_rows = 1 + n_sample_rows + 1

    fig = plt.figure(figsize=(10, 2.5 * total_rows), dpi=150)
    gs = gridspec.GridSpec(total_rows, 3, figure=fig,
                           height_ratios=height_ratios,
                           hspace=0.5, wspace=0.35)

    # --- Top: Survey scan ---
    ax_survey = fig.add_subplot(gs[0, :])
    try:
        x_survey, y_survey = get_scan_xy(spec_datafile, survey_scan)
        ax_survey.plot(x_survey, y_survey, linewidth=1.0, color="#1f77b4")
        ax_survey.scatter(x_survey, y_survey, s=4, alpha=0.5, color="#1f77b4")
        ax_survey.set_xlabel("Sz (mm)", fontsize=8)
        ax_survey.set_ylabel("Signal", fontsize=8)

        # Mark sample positions on survey if available
        for sp in sample_positions:
            sz_center = (sp.get("sz_lo", 0) + sp.get("sz_hi", 0)) / 2
            if sz_center != 0:
                ax_survey.axvline(sz_center, color="#d62728", linewidth=0.8,
                                  linestyle="--", alpha=0.6)
                name = sp.get("sample_name", f"S{sp.get('sample_number', '?')}")
                ax_survey.text(sz_center, ax_survey.get_ylim()[1] * 0.95,
                               name, fontsize=5, ha="center", va="top",
                               rotation=45, color="#d62728")

    except Exception as exc:
        logger.warning("Could not plot survey scan #%d: %s", survey_scan, exc)
        ax_survey.text(0.5, 0.5, f"Survey scan #{survey_scan}: No data",
                       transform=ax_survey.transAxes, ha="center", va="center",
                       fontsize=10, color="#999999")

    ax_survey.set_title(f"Sz Survey (scan #{survey_scan})", fontsize=9, fontweight="bold")
    ax_survey.tick_params(labelsize=6)

    # --- Middle: Per-sample fine alignment plots ---
    sorted_samples = sorted(sample_scans.keys())
    for idx, sample_num in enumerate(sorted_samples):
        row = 1 + idx // 3
        col = idx % 3
        if row >= total_rows - 1:
            break  # out of grid space

        ax = fig.add_subplot(gs[row, col])
        scans_for_sample = sample_scans[sample_num]

        # Find the sample name from positions
        sample_name = f"Sample {sample_num}"
        for sp in sample_positions:
            if sp.get("sample_number") == sample_num:
                sample_name = sp.get("sample_name", sample_name)
                break

        if scans_for_sample:
            # Plot the first scan (typically fine Sz) as the primary
            try:
                x, y = get_scan_xy(spec_datafile, scans_for_sample[0])
                ax.plot(x, y, linewidth=0.8, color="#1f77b4")
                ax.scatter(x, y, s=4, alpha=0.5, color="#1f77b4")
                stats = _compute_scan_stats(x, y)
                if stats["peak_x"] is not None:
                    ax.axvline(stats["peak_x"], color="#d62728",
                               linewidth=0.7, linestyle="--", alpha=0.6)
                sd = get_scan_data(spec_datafile, scans_for_sample[0])
                motor = sd.get("scanned_motor", "")
                ax.set_xlabel(motor, fontsize=6)
            except Exception:
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=8, color="#999999")

            # Annotate number of scans
            ax.text(0.98, 0.96, f"{len(scans_for_sample)} scans",
                    transform=ax.transAxes, fontsize=5, ha="right", va="top",
                    color="#666666")
        else:
            ax.text(0.5, 0.5, "No scans", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="#999999")

        ax.set_title(sample_name, fontsize=7, fontweight="bold")
        ax.tick_params(labelsize=5)

    # Fill empty grid cells
    for idx in range(len(sorted_samples), n_sample_rows * 3):
        row = 1 + idx // 3
        col = idx % 3
        if row < total_rows - 1:
            ax = fig.add_subplot(gs[row, col])
            ax.axis("off")

    # --- Bottom: Position table ---
    ax_table = fig.add_subplot(gs[-1, :])
    ax_table.axis("off")

    if sample_positions:
        header = ["Sample", "SX range", "SY range", "SZ range", "Spots", "Emiss (eV)"]
        table_rows = []
        for sp in sample_positions:
            name = sp.get("sample_name", f"S{sp.get('sample_number', '?')}")
            elem = sp.get("element_symbol", "")
            sx_range = f"{sp.get('sx_lo', 0):.2f} - {sp.get('sx_hi', 0):.2f}"
            sy_range = f"{sp.get('sy_lo', 0):.2f} - {sp.get('sy_hi', 0):.2f}"
            sz_range = f"{sp.get('sz_lo', 0):.2f} - {sp.get('sz_hi', 0):.2f}"
            spots = str(sp.get("total_spots", 1))
            emiss = (f"{sp['emiss_energy_eV']:.1f}"
                     if sp.get("emiss_energy_eV") else "---")
            table_rows.append([f"{name} ({elem})", sx_range, sy_range,
                               sz_range, spots, emiss])

        table = ax_table.table(
            cellText=table_rows, colLabels=header,
            cellLoc="center", loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(6)
        table.scale(1.0, 1.1)
        for j in range(len(header)):
            table[0, j].set_facecolor("#d0d0d0")
            table[0, j].set_text_props(fontweight="bold")
    else:
        ax_table.text(0.5, 0.5, "No sample position data",
                      transform=ax_table.transAxes, ha="center", va="center",
                      fontsize=8, color="#999999")

    filename = f"sample_report_{_timestamp_str()}.png"
    filepath = str(out_path / filename)
    fig.savefig(filepath, bbox_inches="tight", dpi=150)
    plt.close(fig)

    logger.info("Sample report saved to %s", filepath)
    return filepath


def survey_report(
    spec_datafile: str,
    sample_scans: dict,
    sample_positions: list,
    output_dir: str = "/tmp/beamline_reports",
) -> str:
    """Generate the Sample-Surveyor summary image.

    Top half: per-sample mini-axes, each overlaying the XAS scans the
    surveyor took on that sample (typically a 2-scan damage-check pair,
    more if fresh-spot moves happened). Bottom: results table with the
    refined filter, count rate, survey energy, and notes per sample.

    Args:
        spec_datafile: Path to the SPEC data file the survey scans live in.
        sample_scans: {sample_id: [scan_number, ...]} grouping CollectionScan
            rows from the survey window. Iterated in the order of
            ``sample_positions`` so panel layout matches the table.
        sample_positions: List of dicts; each must contain
            ``sample_id``, ``sample_name``, ``element_symbol`` and may
            contain ``xas_filter``, ``survey_counts_per_sec``,
            ``survey_energy_ev``, ``survey_notes``.
        output_dir: Directory to save the PNG.

    Returns:
        Absolute path to the saved PNG file.
    """
    out_path = _ensure_output_dir(output_dir)
    samples = list(sample_positions or [])
    n_samples = max(1, len(samples))

    cols = 3 if n_samples >= 3 else n_samples
    n_panel_rows = max(1, (n_samples + cols - 1) // cols)

    height_ratios = [0.9] * n_panel_rows + [0.45]
    total_rows = n_panel_rows + 1
    fig = plt.figure(figsize=(10, 2.6 * total_rows), dpi=150)
    gs = gridspec.GridSpec(total_rows, cols, figure=fig,
                           height_ratios=height_ratios,
                           hspace=0.55, wspace=0.35)

    overlay_colors = plt.cm.tab10(np.linspace(0, 1, 10))

    for idx, sp in enumerate(samples):
        row = idx // cols
        col = idx % cols
        ax = fig.add_subplot(gs[row, col])

        sid = sp.get("sample_id")
        name = sp.get("sample_name") or f"S{sp.get('sample_number', '?')}"
        elem = sp.get("element_symbol") or ""
        title = f"{name} ({elem})" if elem else name

        scan_nums = list(sample_scans.get(sid, []))
        if not scan_nums:
            ax.text(0.5, 0.5, "No scans", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="#999999")
            ax.set_title(title, fontsize=8, fontweight="bold")
            ax.tick_params(labelsize=6)
            continue

        motor_label = None
        plotted_any = False
        for k, sn in enumerate(scan_nums):
            try:
                x, y = get_scan_xy(spec_datafile, sn)
            except Exception as exc:
                logger.warning("survey_report: skip scan #%d for %s: %s",
                               sn, name, exc)
                continue
            color = overlay_colors[k % len(overlay_colors)]
            ax.plot(x, y, linewidth=0.9, alpha=0.85, color=color,
                    label=f"#{sn}")
            ax.scatter(x, y, s=3, alpha=0.5, color=color)
            if motor_label is None:
                try:
                    sd = get_scan_data(spec_datafile, sn)
                    parsed = parse_scan_command(sd.get("command", ""))
                    motor_label = parsed.get("motor") or ""
                except Exception:
                    motor_label = ""
            plotted_any = True

        if not plotted_any:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=8, color="#999999")
        else:
            ax.legend(fontsize=5, loc="best", frameon=False)
            ax.set_xlabel(motor_label or "energy", fontsize=6)
            ax.set_ylabel("signal", fontsize=6)
        ax.set_title(title, fontsize=8, fontweight="bold")
        ax.tick_params(labelsize=6)

    # Fill empty panel cells so the layout doesn't shift the table.
    for idx in range(len(samples), n_panel_rows * cols):
        row = idx // cols
        col = idx % cols
        ax = fig.add_subplot(gs[row, col])
        ax.axis("off")

    # Results table
    ax_table = fig.add_subplot(gs[-1, :])
    ax_table.axis("off")

    if samples:
        header = ["Sample", "Filter", "Counts/s", "Survey eV", "Notes"]
        rows = []
        for sp in samples:
            name = sp.get("sample_name") or f"S{sp.get('sample_number', '?')}"
            elem = sp.get("element_symbol") or ""
            label = f"{name} ({elem})" if elem else name
            filt = sp.get("xas_filter")
            cps = sp.get("survey_counts_per_sec")
            ev = sp.get("survey_energy_ev")
            notes = sp.get("survey_notes") or ""
            rows.append([
                label,
                str(filt) if filt is not None else "---",
                f"{cps:,.0f}" if cps is not None else "---",
                f"{ev:.1f}" if ev is not None else "---",
                (notes[:60] + "…") if len(notes) > 60 else notes,
            ])
        table = ax_table.table(cellText=rows, colLabels=header,
                               cellLoc="center", loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(6)
        table.scale(1.0, 1.1)
        for j in range(len(header)):
            table[0, j].set_facecolor("#d0d0d0")
            table[0, j].set_text_props(fontweight="bold")
    else:
        ax_table.text(0.5, 0.5, "No survey results recorded",
                      transform=ax_table.transAxes, ha="center", va="center",
                      fontsize=8, color="#999999")

    filename = f"survey_report_{_timestamp_str()}.png"
    filepath = str(out_path / filename)
    fig.savefig(filepath, bbox_inches="tight", dpi=150)
    plt.close(fig)

    logger.info("Survey report saved to %s", filepath)
    return filepath

