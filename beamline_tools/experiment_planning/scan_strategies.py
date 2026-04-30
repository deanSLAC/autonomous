"""
Per-motor scan strategies for BL15-2 beamline alignment.

Each strategy dictionary describes what a good scan looks like for a
specific motor, which fitter to use, what the iteration plan is, and
under which conditions the decision layer should escalate to the LLM.

Strategy keys
-------------
motor : str
    SPEC motor mnemonic.
scan_type : str
    Expected profile shape. One of "aperture" (flat-top with edges),
    "peak" (single Gaussian-like peak), "edge" (knife-edge step).
signal : str
    Which counter column to analyze (e.g. "I0", "I1", "vortDT").
typical_fwhm : tuple[float, float]
    Acceptable (min, max) FWHM range in motor units (mm or eV).
min_peak_counts : int
    Minimum acceptable peak signal intensity.
edge_threshold : float, optional
    Normalized threshold for aperture edge detection (0-1).
iteration_strategy : dict[int, str]
    Maps iteration number to the preferred action. Values are
    "move_to_center" (computed from fit), "peak" (SPEC's peak),
    or "cen" (SPEC's centroid).
fallback : str
    SPEC command to use if Python is unreachable.
escalate_to_llm_when : list[str]
    Issue names (matching FitResult.issues) that should trigger
    LLM consultation.
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Mirror strategies
# ---------------------------------------------------------------------------

MIRROR_M1: dict = {
    "motor": "m1vert",
    "scan_type": "aperture",
    "signal": "I0",
    "typical_fwhm": (0.5, 2.0),        # mm
    "min_peak_counts": 5000,
    "edge_threshold": 0.5,
    "iteration_strategy": {
        1: "move_to_center",
        2: "cen",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "only_one_edge_found",
        "fwhm_outside_range",
        "peak_counts_below_minimum",
        "fit_quality_below_0.8",
    ],
}

MIRROR_M2: dict = {
    "motor": "m2horz",
    "scan_type": "peak",
    "signal": "I0",
    "typical_fwhm": (0.5, 3.0),         # mm
    "min_peak_counts": 5000,
    "iteration_strategy": {
        1: "peak",
        2: "cen",
    },
    "fallback": "peak",
    "escalate_to_llm_when": [
        "peak_at_scan_boundary",
        "multiple_peaks_detected",
        "peak_counts_below_minimum",
    ],
}

# ---------------------------------------------------------------------------
# Mono slit strategies
# ---------------------------------------------------------------------------

SLIT_V: dict = {
    "motor": "monvtra",
    "scan_type": "peak",
    "signal": "I0",
    "typical_fwhm": (0.1, 0.5),         # mm
    "min_peak_counts": 3000,
    "iteration_strategy": {
        1: "peak",
        2: "cen",
    },
    "fallback": "peak",
    "escalate_to_llm_when": [
        "peak_at_scan_boundary",
        "peak_counts_below_minimum",
    ],
}

SLIT_H: dict = {
    "motor": "monhtra",
    "scan_type": "peak",
    "signal": "I0",
    "typical_fwhm": (0.1, 0.5),         # mm
    "min_peak_counts": 3000,
    "iteration_strategy": {
        1: "peak",
        2: "cen",
    },
    "fallback": "peak",
    "escalate_to_llm_when": [
        "peak_at_scan_boundary",
        "peak_counts_below_minimum",
    ],
}

# ---------------------------------------------------------------------------
# B-stage strategies
# ---------------------------------------------------------------------------

BSTAGE_Z: dict = {
    "motor": "Bz",
    "scan_type": "aperture",
    "signal": "I1",
    "typical_fwhm": (3.0, 7.0),         # mm, 5mm aperture
    "min_peak_counts": 8000,
    "edge_threshold": 0.5,
    "iteration_strategy": {
        1: "move_to_center",
        2: "cen",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "only_one_edge_found",
        "fwhm_outside_range",
        "peak_counts_below_minimum",
        "large_move",
    ],
}

BSTAGE_X: dict = {
    "motor": "Bx",
    "scan_type": "aperture",
    "signal": "I1",
    "typical_fwhm": (3.0, 7.0),         # mm, 5mm aperture
    "min_peak_counts": 8000,
    "edge_threshold": 0.5,
    "iteration_strategy": {
        1: "move_to_center",
        2: "cen",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "only_one_edge_found",
        "fwhm_outside_range",
        "peak_counts_below_minimum",
    ],
}

# ---------------------------------------------------------------------------
# Sample stage strategies
# ---------------------------------------------------------------------------

SAMPLE_SZ: dict = {
    "motor": "Sz",
    "scan_type": "peak",
    "signal": "vortDT",
    "typical_fwhm": (0.5, 5.0),         # mm
    "min_peak_counts": 200,
    "iteration_strategy": {
        1: "peak",
        2: "cen",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "peak_at_scan_boundary",
        "multiple_peaks_detected",
        "low_signal",
    ],
}

SAMPLE_SX_EDGE: dict = {
    "motor": "Sx",
    "scan_type": "edge",
    "signal": "vortDT",
    "typical_fwhm": (0.5, 10.0),        # mm
    "min_peak_counts": 100,
    "iteration_strategy": {
        1: "move_to_center",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "no_edges_found",
        "low_signal",
    ],
}

SAMPLE_SY_EDGE: dict = {
    "motor": "Sy",
    "scan_type": "edge",
    "signal": "vortDT",
    "typical_fwhm": (0.5, 10.0),        # mm
    "min_peak_counts": 100,
    "iteration_strategy": {
        1: "move_to_center",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "no_edges_found",
        "low_signal",
    ],
}

# ---------------------------------------------------------------------------
# Emission / spectrometer strategies
# ---------------------------------------------------------------------------

EMISSION_SCAN: dict = {
    "motor": "emiss",
    "scan_type": "emission",
    "signal": "vortDT",
    "typical_fwhm": (0.5, 5.0),         # eV
    "min_peak_counts": 50,
    "iteration_strategy": {
        1: "move_to_center",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "poor_fit",
        "multiple_peaks",
        "low_signal",
    ],
}

# ---------------------------------------------------------------------------
# Master lookup
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, dict] = {
    "m1vert": MIRROR_M1,
    "m2horz": MIRROR_M2,
    "monvtra": SLIT_V,
    "monhtra": SLIT_H,
    "Bz": BSTAGE_Z,
    "Bx": BSTAGE_X,
    "Sz": SAMPLE_SZ,
    "Sx": SAMPLE_SX_EDGE,
    "Sy": SAMPLE_SY_EDGE,
    "emiss": EMISSION_SCAN,
}

# Generic fallback for motors not in the lookup
_DEFAULT_STRATEGY: dict = {
    "motor": "unknown",
    "scan_type": "peak",
    "signal": "I0",
    "typical_fwhm": (0.1, 10.0),
    "min_peak_counts": 100,
    "iteration_strategy": {
        1: "peak",
        2: "cen",
    },
    "fallback": "cen",
    "escalate_to_llm_when": [
        "peak_at_scan_boundary",
        "low_signal",
    ],
}


def get_strategy(motor_name: str) -> dict:
    """Get the scan strategy for a motor.

    Parameters
    ----------
    motor_name : str
        SPEC motor mnemonic (e.g. "m1vert", "Bz", "Sz").

    Returns
    -------
    dict
        Strategy dictionary. Returns a generic default if the motor
        is not in the lookup table.
    """
    strategy = STRATEGIES.get(motor_name)
    if strategy is not None:
        return strategy

    # Return a copy of the default with the motor name filled in
    default = dict(_DEFAULT_STRATEGY)
    default["motor"] = motor_name
    return default
