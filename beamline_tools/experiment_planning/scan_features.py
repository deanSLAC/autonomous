"""Generic per-rep scalar extraction over an agent-supplied energy window.

The agent identifies a feature on the spectrum (white-line peak, pre-edge
shoulder, dip between two oscillations, etc.) and passes the numeric energy
bounds [e_min, e_max] plus a statistic. This module then returns the per-rep
scalar trace, running mean, SEM, and a convergence verdict for that scalar.

This is the primitive the skill leans on when the agent says "is the white-line
height converged" — it's energy-window agnostic; the agent owns the choice of
window and statistic.

Pure math module — no DB, no data loading, no pandas dependency at the
function level (callers pass arrays).
"""

from __future__ import annotations

import numpy as np
from typing import Any

VALID_STATISTICS = {"max", "min", "mean", "median", "integral", "argmax", "argmin", "height"}


def extract_window_scalar(
    scan_2d: list[list[float]],
    energy: list[float],
    e_min: float,
    e_max: float,
    statistic: str = "max",
) -> dict[str, Any]:
    """Reduce each scan to a single scalar over the energy window [e_min, e_max].

    Parameters
    ----------
    scan_2d : list[list[float]]
        Shape (n_scans, n_points). Each row is one rep's spectrum.
    energy : list[float]
        Length n_points. Energy axis (eV).
    e_min, e_max : float
        Inclusive window bounds in eV. Agent-supplied.
    statistic : str
        - "max": peak value in window (white-line height-style)
        - "min": minimum value in window (dip)
        - "mean": average value across window
        - "median": median across window
        - "integral": trapezoidal integral over window (peak area-style)
        - "argmax": energy at which max occurs (edge / peak position)
        - "argmin": energy at which min occurs
        - "height": max - min in window (peak prominence)

    Returns
    -------
    dict with keys:
        - per_rep_values: list of one scalar per scan
        - statistic, e_min, e_max, n_points_in_window
        - error: present if input invalid
    """
    if statistic not in VALID_STATISTICS:
        return {"error": f"Unknown statistic '{statistic}'. Use one of {sorted(VALID_STATISTICS)}."}
    if e_min >= e_max:
        return {"error": f"e_min ({e_min}) must be less than e_max ({e_max})."}

    data = np.array(scan_2d, dtype=float)
    e = np.array(energy, dtype=float)
    if data.ndim != 2:
        return {"error": "scan_2d must be 2D (n_scans, n_points)."}
    if data.shape[1] != e.shape[0]:
        return {"error": f"scan_2d has {data.shape[1]} cols, energy has {e.shape[0]} points."}

    mask = (e >= e_min) & (e <= e_max)
    n_in = int(mask.sum())
    if n_in < 2:
        return {
            "error": (
                f"Window [{e_min}, {e_max}] eV contains only {n_in} points "
                f"(need at least 2). Available range: [{e.min():.2f}, {e.max():.2f}]."
            )
        }

    e_win = e[mask]
    win = data[:, mask]

    if statistic == "max":
        vals = np.max(win, axis=1)
    elif statistic == "min":
        vals = np.min(win, axis=1)
    elif statistic == "mean":
        vals = np.mean(win, axis=1)
    elif statistic == "median":
        vals = np.median(win, axis=1)
    elif statistic == "integral":
        # np.trapz was removed in numpy>=2.0; np.trapezoid is the replacement.
        trap = getattr(np, "trapezoid", None) or np.trapz  # type: ignore[attr-defined]
        vals = trap(win, x=e_win, axis=1)
    elif statistic == "argmax":
        idx = np.argmax(win, axis=1)
        vals = e_win[idx]
    elif statistic == "argmin":
        idx = np.argmin(win, axis=1)
        vals = e_win[idx]
    elif statistic == "height":
        vals = np.max(win, axis=1) - np.min(win, axis=1)

    return {
        "statistic": statistic,
        "e_min": float(e_min),
        "e_max": float(e_max),
        "n_points_in_window": n_in,
        "n_scans": int(data.shape[0]),
        "per_rep_values": [float(v) for v in vals.tolist()],
    }


def analyze_scalar_convergence(
    per_rep_values: list[float],
    sem_threshold_frac: float = 0.01,
    drift_threshold_frac: float = 0.01,
) -> dict[str, Any]:
    """Decide whether a 1D per-rep scalar trace has converged.

    Computes running mean, running SEM (std / sqrt(n)), and the rep-over-rep
    drift in the running mean as fractions of the latest running mean.

    Parameters
    ----------
    per_rep_values : list[float]
        One scalar per rep, in collection order.
    sem_threshold_frac : float, default 0.01
        Converged-SEM target as a fraction of the running mean (1% by default).
        Tighten for publication-quality work where the feature drives a result.
    drift_threshold_frac : float, default 0.01
        Step-to-step drift in running mean (as fraction of latest mean) below
        which the trace is considered stable.

    Returns
    -------
    dict with:
        - n: int
        - running_mean: list[float]
        - running_sem: list[float]
        - running_sem_frac: list[float] (sem / |running_mean|)
        - mean_step_frac: list[float] (step-to-step running-mean change / |latest|)
        - final_mean, final_sem, final_sem_frac, final_drift_frac
        - verdict: "needs_more" | "marginal" | "converged"
        - verdict_explanation: str
    """
    vals = np.array(per_rep_values, dtype=float)
    n = vals.size
    if n < 2:
        return {"error": f"Need at least 2 reps, got {n}."}

    running_mean = np.array([np.mean(vals[: i + 1]) for i in range(n)])
    # SEM defined for n>=2; report 0 for n=1 row
    running_std = np.array([np.std(vals[: i + 1], ddof=1) if i >= 1 else 0.0 for i in range(n)])
    running_sem = running_std / np.sqrt(np.arange(1, n + 1))

    with np.errstate(divide="ignore", invalid="ignore"):
        running_sem_frac = np.where(
            np.abs(running_mean) > 1e-15,
            running_sem / np.abs(running_mean),
            np.inf,
        )
        mean_step = np.zeros(n)
        for i in range(1, n):
            denom = abs(running_mean[i]) if abs(running_mean[i]) > 1e-15 else 1.0
            mean_step[i] = abs(running_mean[i] - running_mean[i - 1]) / denom

    final_sem_frac = float(running_sem_frac[-1])
    final_drift_frac = float(mean_step[-1])

    if not np.isfinite(final_sem_frac):
        verdict = "needs_more"
        explanation = "Running mean is ~0; cannot compute fractional SEM."
    elif final_sem_frac < sem_threshold_frac and final_drift_frac < drift_threshold_frac:
        verdict = "converged"
        explanation = (
            f"SEM is {final_sem_frac:.3%} of mean (target <{sem_threshold_frac:.1%}) and "
            f"running mean has stabilized (step {final_drift_frac:.3%} < {drift_threshold_frac:.1%})."
        )
    elif final_sem_frac < 2 * sem_threshold_frac and final_drift_frac < 2 * drift_threshold_frac:
        verdict = "marginal"
        explanation = (
            f"SEM is {final_sem_frac:.3%} of mean and last step is {final_drift_frac:.3%} — "
            f"approaching but not at the convergence target."
        )
    else:
        verdict = "needs_more"
        explanation = (
            f"SEM is {final_sem_frac:.3%} of mean (target <{sem_threshold_frac:.1%}) "
            f"and/or running mean still drifting {final_drift_frac:.3%} per rep "
            f"(target <{drift_threshold_frac:.1%}). More reps recommended."
        )

    return {
        "n": int(n),
        "running_mean": [round(v, 8) for v in running_mean.tolist()],
        "running_sem": [round(v, 8) for v in running_sem.tolist()],
        "running_sem_frac": [
            round(v, 8) if np.isfinite(v) else None for v in running_sem_frac.tolist()
        ],
        "mean_step_frac": [round(v, 8) for v in mean_step.tolist()],
        "final_mean": float(running_mean[-1]),
        "final_sem": float(running_sem[-1]),
        "final_sem_frac": final_sem_frac if np.isfinite(final_sem_frac) else None,
        "final_drift_frac": final_drift_frac,
        "verdict": verdict,
        "verdict_explanation": explanation,
    }


def analyze_feature_evolution(
    scan_2d: list[list[float]],
    energy: list[float],
    e_min: float,
    e_max: float,
    statistic: str = "max",
    sem_threshold_frac: float = 0.01,
    drift_threshold_frac: float = 0.01,
) -> dict[str, Any]:
    """Convenience: extract the per-rep scalar over the window and run
    convergence analysis on it. Single call answering "has feature X
    converged?" given numeric energy bounds.
    """
    extract = extract_window_scalar(scan_2d, energy, e_min, e_max, statistic)
    if "error" in extract:
        return extract
    conv = analyze_scalar_convergence(
        extract["per_rep_values"],
        sem_threshold_frac=sem_threshold_frac,
        drift_threshold_frac=drift_threshold_frac,
    )
    if "error" in conv:
        return conv
    return {
        "feature": {
            "statistic": statistic,
            "e_min": float(e_min),
            "e_max": float(e_max),
            "n_points_in_window": extract["n_points_in_window"],
        },
        "per_rep_values": extract["per_rep_values"],
        **conv,
    }


def heterogeneity_f_statistic(
    per_spot_groups: list[list[list[float]]],
) -> dict[str, Any]:
    """One-way ANOVA F-stat across spots, on a windowed scan stack.

    Each group is a 2D array (n_reps_in_spot, n_points). For each energy point
    we compute between-spot variance / within-spot variance, then average over
    energy. F >> 1 means real heterogeneity (spots disagree more than reps
    within a spot); F ~ 1 means spots are statistically indistinguishable.

    Parameters
    ----------
    per_spot_groups : list[list[list[float]]]
        len = n_spots. Each entry is a 2D (n_reps_in_spot, n_points) array.
        Each spot must have >= 2 reps. All groups must share n_points.

    Returns
    -------
    dict with f_stat (averaged over energy points), per_point_f (list),
    n_spots, n_total_reps, verdict in {"homogeneous", "borderline",
    "heterogeneous"}, verdict_explanation.
    """
    if len(per_spot_groups) < 2:
        return {"error": f"Need at least 2 spots, got {len(per_spot_groups)}."}

    arrays = [np.array(g, dtype=float) for g in per_spot_groups]
    n_points_set = {a.shape[1] for a in arrays}
    if len(n_points_set) != 1:
        return {"error": f"All spots must share n_points; got {n_points_set}."}
    n_points = n_points_set.pop()

    n_reps_per_spot = np.array([a.shape[0] for a in arrays])
    n_total = int(n_reps_per_spot.sum())
    n_spots = len(arrays)
    if np.any(n_reps_per_spot < 2):
        return {
            "error": (
                f"Each spot must have >= 2 reps. Got per-spot rep counts: "
                f"{n_reps_per_spot.tolist()}."
            )
        }

    spot_means = np.stack([a.mean(axis=0) for a in arrays], axis=0)  # (n_spots, n_points)
    grand_mean = np.average(spot_means, axis=0, weights=n_reps_per_spot)  # (n_points,)

    # Between-spot SS at each energy point: sum_s n_s (mean_s - grand_mean)^2
    ss_between = np.sum(
        n_reps_per_spot[:, None] * (spot_means - grand_mean[None, :]) ** 2,
        axis=0,
    )
    # Within-spot SS: sum_s sum_r (x_sr - mean_s)^2
    ss_within = np.zeros(n_points)
    for spot_arr, spot_mean in zip(arrays, spot_means):
        ss_within += np.sum((spot_arr - spot_mean[None, :]) ** 2, axis=0)

    df_between = n_spots - 1
    df_within = n_total - n_spots
    if df_within <= 0 or df_between <= 0:
        return {"error": "Insufficient degrees of freedom for F statistic."}

    ms_between = ss_between / df_between
    ms_within = ss_within / df_within
    with np.errstate(divide="ignore", invalid="ignore"):
        per_point_f = np.where(ms_within > 0, ms_between / ms_within, np.nan)

    finite = per_point_f[np.isfinite(per_point_f)]
    f_stat = float(np.mean(finite)) if finite.size else float("nan")

    if not np.isfinite(f_stat):
        verdict = "unknown"
        explanation = "Unable to compute F (zero within-spot variance everywhere)."
    elif f_stat < 2.0:
        verdict = "homogeneous"
        explanation = (
            f"F={f_stat:.2f} (target <2): spot-to-spot differences are within shot noise; "
            f"reps from different spots can be safely averaged together."
        )
    elif f_stat < 5.0:
        verdict = "borderline"
        explanation = (
            f"F={f_stat:.2f} (2-5): spots may differ slightly. Inspect per-spot averages "
            f"visually; if they differ at any feature, treat as heterogeneous."
        )
    else:
        verdict = "heterogeneous"
        explanation = (
            f"F={f_stat:.2f} (>>1): spots disagree well beyond shot noise. The combined "
            f"average is a population mean, not a single-chemistry spectrum. More reps "
            f"will not converge a single chemistry — consider analyzing per-spot."
        )

    return {
        "n_spots": n_spots,
        "n_total_reps": n_total,
        "n_reps_per_spot": n_reps_per_spot.tolist(),
        "df_between": int(df_between),
        "df_within": int(df_within),
        "f_stat": round(f_stat, 4),
        "per_point_f": [
            round(v, 4) if np.isfinite(v) else None for v in per_point_f.tolist()
        ],
        "verdict": verdict,
        "verdict_explanation": explanation,
    }
