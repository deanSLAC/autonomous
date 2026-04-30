"""
MCP tool for cosine similarity analysis of scan data.

Exposes the cosine similarity metrics from the SNR monitor as an MCP tool
for use by an LLM chatbot. Accepts a 2D array of scan intensity data
(rows = scans, columns = energy/measurement points) and returns:
- Individual vs mean similarity (per-scan)
- Cumulative convergence similarity
- Standard error of the mean
"""

import numpy as np
from typing import Any


def compute_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Cosine similarity between two vectors: (A . B) / (||A|| * ||B||)."""
    v1 = vec1.flatten()
    v2 = vec2.flatten()
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def analyze_scan_quality(scan_data: list[list[float]]) -> dict[str, Any]:
    """
    Analyze scan quality using cosine similarity and standard error metrics.

    This tool takes a 2D array of scan intensity data and computes three metrics:

    1. **individual_vs_mean**: Cosine similarity of each scan to the overall mean.
       Values near 1.0 indicate the scan agrees with the average; low values flag outliers.

    2. **cumulative_convergence**: Cosine similarity between consecutive cumulative
       averages. Values approaching 1.0 indicate the measurement is converging.
       A threshold of >= 0.99 suggests good convergence.

    3. **standard_error_of_mean**: Average SEM across measurement points for
       successive cumulative averages. Should decrease as ~1/sqrt(n).

    Parameters
    ----------
    scan_data : list[list[float]]
        2D array where each inner list is one scan (row) and contains intensity
        values at each energy/measurement point (columns).
        Shape: (n_scans, n_points). Minimum 2 scans required.

    Returns
    -------
    dict with keys:
        - n_scans: int
        - n_points: int
        - individual_vs_mean: list[float] — per-scan similarity to the mean
        - cumulative_convergence: list[float] — convergence of running averages
        - standard_error_of_mean: list[float] — SEM for successive averages
        - summary: str — human-readable interpretation
    """
    data = np.array(scan_data, dtype=float)
    if data.ndim != 2 or data.shape[0] < 2:
        return {"error": "scan_data must be a 2D array with at least 2 scans (rows)."}

    n_scans, n_points = data.shape

    # Individual vs mean
    overall_mean = np.mean(data, axis=0)
    individual_sim = [compute_cosine_similarity(data[i], overall_mean) for i in range(n_scans)]

    # Cumulative convergence
    convergence = [1.0]
    for i in range(1, n_scans):
        avg_curr = np.mean(data[:i + 1], axis=0)
        avg_prev = np.mean(data[:i], axis=0)
        convergence.append(compute_cosine_similarity(avg_curr, avg_prev))

    # Standard error of the mean
    sem_values = []
    for i in range(n_scans):
        n = i + 1
        subset = data[:n]
        std = np.std(subset, axis=0, ddof=0)
        sem = std / np.sqrt(n)
        sem_values.append(float(np.mean(sem)))

    # Build summary
    min_sim = min(individual_sim)
    final_conv = convergence[-1]
    outliers = [i for i, s in enumerate(individual_sim) if s < 0.95]

    summary_parts = [f"{n_scans} scans, {n_points} points per scan."]
    if final_conv >= 0.99:
        summary_parts.append(f"Cumulative average has converged (final similarity: {final_conv:.6f}).")
    else:
        summary_parts.append(f"Cumulative average has NOT yet converged (final similarity: {final_conv:.6f}, target >= 0.99).")
    if outliers:
        summary_parts.append(f"Potential outlier scans (similarity < 0.95): {outliers}.")
    else:
        summary_parts.append(f"No outlier scans detected (min similarity: {min_sim:.6f}).")
    summary_parts.append(f"Final SEM: {sem_values[-1]:.6g}.")

    return {
        "n_scans": n_scans,
        "n_points": n_points,
        "individual_vs_mean": [round(v, 8) for v in individual_sim],
        "cumulative_convergence": [round(v, 8) for v in convergence],
        "standard_error_of_mean": [round(v, 8) for v in sem_values],
        "summary": " ".join(summary_parts),
    }
