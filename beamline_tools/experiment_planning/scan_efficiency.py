"""
Comprehensive scan repetition efficiency analysis.

Parent tool that calls cosine similarity convergence as one component,
then adds CV analysis, Poisson limit comparison, optimal scan count
recommendation, and a synthesized verdict.

Pure math module — no DB, no data loading, no pandas dependency.
"""

import numpy as np
import warnings
from typing import Any

from beamline_tools.generic_data.cosine_similarity import analyze_scan_quality


def analyze_scan_efficiency(
    scan_data: list[list[float]],
    efficiency_threshold: float = 0.05,
    min_recommended_scans: int = 2,
) -> dict[str, Any]:
    """
    Comprehensive efficiency analysis for repeated scan data.

    Combines cosine similarity convergence with CV analysis, Poisson limit
    comparison, and optimal scan count recommendation.

    Parameters
    ----------
    scan_data : list[list[float]]
        2D array where each row is one scan's normalized intensity values.
        Shape: (n_scans, n_points). Minimum 2 scans required.
    efficiency_threshold : float, default=0.05
        Fractional CV improvement below which adding scans is not worthwhile.
    min_recommended_scans : int, default=2
        Floor for the optimal scan count recommendation.

    Returns
    -------
    dict with keys:
        - convergence: full result from analyze_scan_quality
        - cv_mean_pct: average coefficient of variation (%)
        - poisson_limit_pct: how close to theoretical Poisson limit (%)
        - optimal_scan_count: recommended number of scans
        - marginal_improvement: per-scan fractional CV improvement
        - current_vs_optimal: human-readable comparison string
        - verdict: "needs_more" | "reasonable" | "marginal" | "wasteful"
        - verdict_explanation: human-readable reasoning
    """
    data = np.array(scan_data, dtype=float)
    if data.ndim != 2 or data.shape[0] < 2:
        return {"error": "scan_data must be a 2D array with at least 2 scans (rows)."}

    n_scans, n_points = data.shape

    # --- Component 1: Cosine similarity convergence ---
    convergence_result = analyze_scan_quality(scan_data)
    if "error" in convergence_result:
        return convergence_result

    # --- Component 2: CV analysis ---
    mean_spectrum = np.mean(data, axis=0)
    std_spectrum = np.std(data, axis=0, ddof=1)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv_by_point = std_spectrum / mean_spectrum
        cv_by_point = np.where(np.isfinite(cv_by_point), cv_by_point, 0.0)

    # Trim 5% from each edge to avoid low-signal regions
    trim = max(1, n_points // 20)
    cv_mean = float(np.mean(cv_by_point[trim:-trim])) if n_points > 2 * trim else float(np.mean(cv_by_point))

    # --- Component 3: Cumulative CV improvement curve ---
    cumulative_cv = np.zeros(n_scans)
    for n in range(1, n_scans + 1):
        subset = data[:n]
        cum_mean = np.mean(subset, axis=0)
        if n > 1:
            cum_sem = np.std(subset, axis=0, ddof=1) / np.sqrt(n)
        else:
            cum_sem = std_spectrum
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cum_cv = cum_sem / cum_mean
            cum_cv = np.where(np.isfinite(cum_cv), cum_cv, 0.0)
        if n_points > 2 * trim:
            cumulative_cv[n - 1] = np.mean(cum_cv[trim:-trim])
        else:
            cumulative_cv[n - 1] = np.mean(cum_cv)

    # --- Component 4: Poisson limit comparison ---
    baseline_cv = cumulative_cv[0]
    if baseline_cv > 0 and cumulative_cv[-1] > 0:
        actual_improvement = baseline_cv / cumulative_cv[-1]
        theoretical_improvement = np.sqrt(n_scans)
        poisson_limit_pct = float((actual_improvement / theoretical_improvement) * 100)
    else:
        poisson_limit_pct = 100.0

    # --- Component 5: Marginal improvement & optimal scan count ---
    marginal_improvement = np.zeros(n_scans)
    marginal_improvement[0] = 1.0
    for i in range(1, n_scans):
        if cumulative_cv[i - 1] > 0:
            marginal_improvement[i] = (cumulative_cv[i - 1] - cumulative_cv[i]) / cumulative_cv[i - 1]
        else:
            marginal_improvement[i] = 0.0

    # Find knee: first point where marginal improvement drops below threshold
    optimal_idx = n_scans - 1
    for i in range(min_recommended_scans - 1, n_scans):
        if marginal_improvement[i] < efficiency_threshold:
            optimal_idx = max(i - 1, min_recommended_scans - 1)
            break
    optimal_scan_count = optimal_idx + 1

    # --- Component 6: Verdict ---
    final_convergence = convergence_result["cumulative_convergence"][-1]
    last_marginal = marginal_improvement[-1] if n_scans > 1 else 1.0

    if final_convergence < 0.99 and last_marginal > efficiency_threshold:
        verdict = "needs_more"
        explanation = (
            f"Data has not yet converged (similarity {final_convergence:.4f}, target >= 0.99) "
            f"and scans are still improving significantly ({last_marginal:.1%} per scan). "
            f"More scans are recommended."
        )
    elif n_scans <= optimal_scan_count * 1.2:
        verdict = "reasonable"
        explanation = (
            f"Collecting {n_scans} scans is close to the estimated optimal of {optimal_scan_count}. "
            f"Good balance of statistics and beam time."
        )
    elif n_scans <= optimal_scan_count * 1.5:
        verdict = "marginal"
        explanation = (
            f"Collecting {n_scans} scans when ~{optimal_scan_count} would suffice. "
            f"The extra scans provide diminishing returns."
        )
    else:
        verdict = "wasteful"
        explanation = (
            f"Collecting {n_scans} scans when ~{optimal_scan_count} would give nearly identical statistics. "
            f"The additional {n_scans - optimal_scan_count} scans provide minimal improvement."
        )

    return {
        "convergence": convergence_result,
        "n_scans": n_scans,
        "n_points": n_points,
        "cv_mean_pct": round(cv_mean * 100, 4),
        "poisson_limit_pct": round(poisson_limit_pct, 1),
        "optimal_scan_count": optimal_scan_count,
        "marginal_improvement": [round(v, 6) for v in marginal_improvement.tolist()],
        "cumulative_cv_pct": [round(v * 100, 4) for v in cumulative_cv.tolist()],
        "current_vs_optimal": f"{n_scans} scans collected, {optimal_scan_count} recommended",
        "verdict": verdict,
        "verdict_explanation": explanation,
    }
