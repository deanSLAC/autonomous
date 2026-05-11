"""Plotting functions for scan data."""

import io
import base64
import logging

logger = logging.getLogger(__name__)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import scans


def plot_scan(file_name, scan_number, counter=None, normalize_by=None):
    """Plot a scan and return the figure + text summary.

    If counter is not specified, auto-detects the active counter.

    Returns:
        (fig, summary) -- matplotlib Figure and a text description of the plot.
        Returns (None, error_message) if the scan can't be loaded.
    """
    df = scans.read_processed_scan(file_name, scan_number)
    if df is None:
        return None, f"Scan not found: {file_name} #{scan_number}"

    # Auto-detect active counter when none specified
    if not counter:
        active = scans.get_active_counter(file_name, scan_number)
        if active:
            counter = active["active_counter"]

    meta = scans.get_scan_metadata(file_name, scan_number)

    fig, ax = plt.subplots(figsize=(8, 5))

    x_label = df.index.name or "index"

    if counter:
        if counter not in df.columns:
            available = list(df.columns)
            plt.close(fig)
            return None, f"Counter '{counter}' not found. Available: {available}"
        y = df[counter]
        if normalize_by:
            if normalize_by not in df.columns:
                plt.close(fig)
                return None, f"Normalization counter '{normalize_by}' not found."
            y = y / df[normalize_by]
            y_label = f"{counter}/{normalize_by}"
        else:
            y_label = counter
        ax.plot(df.index, y)
        ax.set_ylabel(y_label)
    else:
        for col in df.columns:
            ax.plot(df.index, df[col], label=col)
        ax.legend(fontsize=8)
        y_label = "counts"

    ax.set_xlabel(x_label)

    title = f"{file_name} scan #{scan_number}"
    if meta and meta.get("scan_command"):
        title += f"\n{meta['scan_command']}"
    ax.set_title(title, fontsize=10)

    fig.tight_layout()

    # Build text summary
    parts = [
        f"Plot of {file_name} scan #{scan_number}",
        f"X axis: {x_label} ({len(df)} points)",
    ]
    if counter:
        parts.append(f"Y axis: {y_label}")
        parts.append(f"Range: {float(y.min()):.4g} to {float(y.max()):.4g}")
    else:
        parts.append(f"Counters plotted: {list(df.columns)}")
    if meta and meta.get("scan_command"):
        parts.append(f"Command: {meta['scan_command']}")

    summary = ". ".join(parts) + "."
    return fig, summary


def plot_averaged_scans_overlay(file_names):
    """Plot edge-step-normalized averaged energy scans for multiple samples.

    Each sample is plotted as a separate line on the same axes.
    Alignment files are skipped.

    Args:
        file_names: List of SPEC file names (one per sample).

    Returns:
        (fig, summary) or (None, error_message).
    """
    import numpy as np

    skip = {"alignment", "alignment_Fe"}
    sample_names = [fn for fn in file_names if fn not in skip]

    if not sample_names:
        return None, "No non-alignment samples to plot."

    fig, ax = plt.subplots(figsize=(10, 6))
    plotted = []

    for fn in sample_names:
        result = scans.average_energy_scans(file_name=fn)
        if not result or "error" in result:
            logger.info("Skipping %s: %s", fn, result.get("error") if result else "no result")
            continue
        # Parse the string data back into arrays for plotting
        lines = result["data"].strip().split("\n")
        energies, averages, stds = [], [], []
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 2:
                energies.append(float(parts[0]))
                averages.append(float(parts[1]))
                stds.append(float(parts[2]) if len(parts) >= 3 else 0.0)
        if not energies:
            continue
        energies_arr = np.array(energies)
        avg_arr = np.array(averages)
        std_arr = np.array(stds)
        label = f"{fn} ({result['num_scans_averaged']} scans)"
        line, = ax.plot(energies_arr, avg_arr, label=label, linewidth=1.2)
        if std_arr.any():
            ax.fill_between(energies_arr, avg_arr - std_arr, avg_arr + std_arr,
                            alpha=0.15, color=line.get_color())
        plotted.append(fn)

    if not plotted:
        plt.close(fig)
        return None, "No valid averaged scans to plot."

    ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("Normalized absorption")
    ax.set_title("Averaged Energy Scans", fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    summary = (
        f"Overlay of averaged energy scans for {len(plotted)} sample(s): "
        f"{', '.join(plotted)}."
    )
    return fig, summary


def plot_scan_stack(file_name, e_min=None, e_max=None):
    """Overlay all reps of one file on a single axis, color-progressed by rep order.

    Each rep is edge-step normalized (the standard pipeline) before plotting,
    so the y-axis is comparable across reps and across spots.

    e_min, e_max are optional numeric eV bounds; when provided, the plot is
    cropped to that window so the agent can inspect a feature directly.
    """
    import numpy as np

    try:
        combined, file_name, counter, used = scans.get_normalized_scan_arrays(
            file_name, e_min=e_min, e_max=e_max,
        )
    except ValueError as e:
        return None, f"Could not load scans for {file_name}: {e}"
    if combined.shape[1] < 2:
        return None, f"Need >= 2 reps to make a stack plot, got {combined.shape[1]}."

    fig, ax = plt.subplots(figsize=(10, 6))
    n_reps = combined.shape[1]
    cmap = plt.get_cmap("viridis")
    for i, col in enumerate(combined.columns):
        color = cmap(i / max(n_reps - 1, 1))
        ax.plot(combined.index, combined[col], color=color, alpha=0.7, linewidth=1.0,
                label=col if n_reps <= 12 else None)

    ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("Edge-step normalized signal")
    title = f"{file_name} — stacked reps ({n_reps} scans, counter={counter})"
    if e_min is not None and e_max is not None:
        title += f"  window=[{e_min:.1f}, {e_max:.1f}] eV"
    ax.set_title(title, fontsize=10)
    if n_reps <= 12:
        ax.legend(fontsize=7, ncol=2)
    else:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=1, vmax=n_reps))
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, pad=0.02)
        cb.set_label("rep #")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig, (
        f"Stacked reps: {file_name} ({n_reps} scans)" +
        (f" windowed to [{e_min}, {e_max}] eV" if e_min is not None else "")
    )


def plot_first_half_vs_second_half(file_name, e_min=None, e_max=None):
    """Compare the average of the first half of reps to the second half, with
    SEM bands. Visual cross-check for whether reps are stationary or drifting.
    """
    import numpy as np

    try:
        combined, file_name, counter, used = scans.get_normalized_scan_arrays(
            file_name, e_min=e_min, e_max=e_max,
        )
    except ValueError as e:
        return None, f"Could not load scans for {file_name}: {e}"
    n = combined.shape[1]
    if n < 4:
        return None, f"Need >= 4 reps for half-vs-half comparison, got {n}."

    half = n // 2
    first = combined.iloc[:, :half]
    second = combined.iloc[:, half:]

    m1 = first.mean(axis=1).values
    s1 = (first.std(axis=1) / np.sqrt(half)).values
    m2 = second.mean(axis=1).values
    s2 = (second.std(axis=1) / np.sqrt(n - half)).values
    energy = combined.index.values

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(energy, m1, label=f"first {half} reps", color="C0", linewidth=1.4)
    ax.fill_between(energy, m1 - s1, m1 + s1, color="C0", alpha=0.2)
    ax.plot(energy, m2, label=f"last {n - half} reps", color="C3", linewidth=1.4)
    ax.fill_between(energy, m2 - s2, m2 + s2, color="C3", alpha=0.2)

    diff = m2 - m1
    sem_combined = np.sqrt(s1**2 + s2**2)
    n_sigma_max = float(np.nanmax(np.abs(diff) / np.where(sem_combined > 0, sem_combined, 1.0)))

    ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("Edge-step normalized signal")
    title = (
        f"{file_name} — first vs second half (max |Δ|/SEM = {n_sigma_max:.1f}σ)"
    )
    if e_min is not None and e_max is not None:
        title += f"  window=[{e_min:.1f}, {e_max:.1f}]"
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    summary = (
        f"First-half vs second-half: max |Δ|/SEM = {n_sigma_max:.2f} sigma. "
        f"<2 sigma: halves agree; >3 sigma: halves disagree at some feature, "
        f"more reps may not help (drift, damage, or heterogeneity)."
    )
    return fig, summary


def plot_running_average(file_name, e_min=None, e_max=None):
    """Plot the running average and SEM band as more reps accumulate, on the
    given window. One line per cumulative subset (1..n reps), color-progressed.
    """
    import numpy as np

    try:
        combined, file_name, counter, used = scans.get_normalized_scan_arrays(
            file_name, e_min=e_min, e_max=e_max,
        )
    except ValueError as e:
        return None, f"Could not load scans for {file_name}: {e}"
    n = combined.shape[1]
    if n < 2:
        return None, f"Need >= 2 reps for running average, got {n}."

    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.get_cmap("viridis")
    energy = combined.index.values
    for i in range(2, n + 1):
        subset = combined.iloc[:, :i]
        m = subset.mean(axis=1).values
        color = cmap(i / max(n, 1))
        ax.plot(energy, m, color=color, alpha=0.7, linewidth=0.9)

    final_mean = combined.mean(axis=1).values
    final_sem = (combined.std(axis=1) / np.sqrt(n)).values
    ax.fill_between(energy, final_mean - final_sem, final_mean + final_sem,
                    color="black", alpha=0.15, label=f"final ±SEM (n={n})")

    ax.set_xlabel("Energy (eV)")
    ax.set_ylabel("Edge-step normalized running mean")
    title = f"{file_name} — running average through {n} reps"
    if e_min is not None and e_max is not None:
        title += f"  window=[{e_min:.1f}, {e_max:.1f}]"
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=2, vmax=n))
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.02)
    cb.set_label("running sum through rep #")
    fig.tight_layout()
    return fig, f"Running average through {n} reps; band = final ±SEM."


def plot_feature_evolution(file_name, e_min, e_max, statistic="max"):
    """Plot a single per-rep scalar (the chosen statistic over [e_min, e_max])
    versus rep number, with running mean and ±SEM band overlaid.

    Agent must supply numeric e_min and e_max — this function does not infer
    a window. Useful statistics: "max" (white-line height), "argmax" (white-line
    position), "integral" (peak area), "min" / "argmin" (dip), "height" (max−min).
    """
    import numpy as np
    from beamline_tools.experiment_planning.scan_features import (
        extract_window_scalar, analyze_scalar_convergence,
    )

    try:
        combined, file_name, counter, used = scans.get_normalized_scan_arrays(file_name)
    except ValueError as e:
        return None, f"Could not load scans for {file_name}: {e}"
    n = combined.shape[1]
    if n < 2:
        return None, f"Need >= 2 reps for feature evolution, got {n}."

    clean = combined.dropna()
    energy = clean.index.values.tolist()
    scan_2d = clean.values.T.tolist()
    extract = extract_window_scalar(scan_2d, energy, e_min, e_max, statistic)
    if "error" in extract:
        return None, extract["error"]
    vals = np.array(extract["per_rep_values"])
    conv = analyze_scalar_convergence(vals.tolist())
    running_mean = np.array(conv["running_mean"])
    running_sem = np.array(conv["running_sem"])
    rep_idx = np.arange(1, len(vals) + 1)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(rep_idx, vals, "o", color="C0", label=f"per-rep {statistic} in window")
    ax.plot(rep_idx, running_mean, "-", color="C3", linewidth=1.5, label="running mean")
    ax.fill_between(rep_idx, running_mean - running_sem, running_mean + running_sem,
                    color="C3", alpha=0.2, label="±SEM")
    ax.set_xlabel("Rep #")
    ax.set_ylabel(f"{statistic} over [{e_min}, {e_max}] eV")
    title = (
        f"{file_name} — feature {statistic} evolution "
        f"(verdict: {conv['verdict']}, SEM={conv['final_sem_frac']:.2%} of mean, "
        f"last drift={conv['final_drift_frac']:.2%})"
    )
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig, (
        f"Feature evolution ({statistic} on [{e_min}, {e_max}] eV): "
        f"verdict={conv['verdict']}, final mean={conv['final_mean']:.4g}, "
        f"final SEM={conv['final_sem']:.4g} ({conv['final_sem_frac']:.2%} of mean), "
        f"last running-mean step={conv['final_drift_frac']:.2%}."
    )


def plot_statistics_trend(stats, sample_name=""):
    """Render a two-subplot statistics trend from pre-computed convergence stats.

    Parameters
    ----------
    stats : dict
        convergence_stats dict stored per-sample in the plan JSON. Expected
        keys: feature_window_eV, cumulative_cv_pct, running_sem_frac,
        efficiency_verdict, feature_verdict, statistic.
    sample_name : str
        Sample name for the plot title.

    Returns
    -------
    (fig, summary_text) or (None, error_text)
    """
    import numpy as np

    cv_pct = stats.get("cumulative_cv_pct")
    sem_frac = stats.get("running_sem_frac")
    if not cv_pct or not sem_frac:
        return None, "convergence_stats missing cumulative_cv_pct or running_sem_frac"

    n = len(cv_pct)
    reps = np.arange(1, n + 1)
    cv_arr = np.array(cv_pct, dtype=float)
    sem_arr = np.array([(v if v is not None else np.nan) for v in sem_frac], dtype=float) * 100

    window = stats.get("feature_window_eV") or [None, None]
    sem_threshold = stats.get("sem_threshold_frac", 0.01) * 100
    eff_verdict = stats.get("efficiency_verdict", "?")
    feat_verdict = stats.get("feature_verdict", "?")

    fig, (ax_cv, ax_sem) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    # --- Top: Cumulative CV ---
    ax_cv.plot(reps, cv_arr, "o-", color="C0", markersize=4, label="Cumulative CV")
    poisson_cv = cv_arr[0] / np.sqrt(reps)
    ax_cv.plot(reps, poisson_cv, "--", color="gray", alpha=0.7, label="1/√n Poisson")
    ax_cv.set_ylabel("Cumulative CV (%)")
    ax_cv.legend(fontsize=7, loc="upper right")
    ax_cv.grid(alpha=0.3)

    # --- Bottom: Feature SEM ---
    # Rep 1 has SEM=0 by definition (single sample); skip it so the
    # axis isn't pinned to zero.
    sem_reps = reps[1:]
    sem_vals = sem_arr[1:]
    ax_sem.plot(sem_reps, sem_vals, "o-", color="C0", markersize=4,
                label="Feature SEM (% of mean)")
    finite_mask = np.isfinite(sem_vals) & (sem_vals > 0)
    if finite_mask.sum() >= 2:
        first = int(np.where(finite_mask)[0][0])
        anchor = sem_vals[first]
        anchor_rep = sem_reps[first]
        poisson_sem = anchor * np.sqrt(anchor_rep) / np.sqrt(sem_reps)
        ax_sem.plot(sem_reps, poisson_sem, "--", color="gray", alpha=0.7,
                    label="1/√n Poisson")
    ax_sem.axhline(sem_threshold, color="C1", linestyle="-", alpha=0.6,
                   label=f"{sem_threshold:.0f}% publication threshold")
    ax_sem.set_ylabel("SEM (% of mean)")
    ax_sem.set_xlabel("Rep #")
    ax_sem.legend(fontsize=7, loc="upper right")
    ax_sem.grid(alpha=0.3)

    e_min, e_max = window
    window_str = f"[{e_min}, {e_max}] eV" if e_min is not None else ""
    title = (
        f"{sample_name} — statistics trend {window_str} "
        f"(CV: {eff_verdict}, SEM: {feat_verdict})"
    )
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()

    summary = (
        f"Statistics trend for {sample_name}: "
        f"CV verdict={eff_verdict}, feature verdict={feat_verdict}, "
        f"final CV={cv_arr[-1]:.2f}%, final SEM={sem_arr[-1]:.2f}%."
    )
    return fig, summary


def fig_to_base64(fig):
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()
