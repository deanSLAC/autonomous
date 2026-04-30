"""
Decision layer for BL15-2 beamline scan analysis.

Takes scan data from spec_reader, runs the appropriate fitter, applies
the motor's strategy, and returns a concrete SPEC command. Optionally
consults the LLM advisor when deterministic analysis is ambiguous.

This module is called by the FastAPI server endpoints (/decide/*).
"""

import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

from beamline_tools.generic_data.fitter import (
    FitResult,
    fit_aperture_edges,
    fit_peak,
    fit_knife_edge,
    detect_peaks_survey,
    fit_emission_peak,
)
from .scan_strategies import get_strategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScanDecision:
    """A decision about what SPEC command to execute after a scan.

    Attributes
    ----------
    action : str
        High-level action type. One of: "move", "peak", "cen",
        "rescan", "accept", "alert".
    command : str
        SPEC command string to execute, e.g. ``"umv m1vert 1.93"``
        or ``"peak"`` or ``"dscan m1vert -2.5 1.0 70 0.2"``.
    reason : str
        Human-readable explanation of the decision.
    confidence : float
        Decision confidence from 0 (guessing) to 1 (certain).
    llm_consulted : bool
        Whether the LLM was involved in making this decision.
    fit_result : Optional[dict]
        Serialized FitResult for logging/DB storage.
    """

    action: str
    command: str
    reason: str
    confidence: float
    llm_consulted: bool = False
    fit_result: Optional[dict] = None


# ---------------------------------------------------------------------------
# Move thresholds for deciding if another iteration is needed
# ---------------------------------------------------------------------------

_ITERATION_MOVE_THRESHOLDS: dict[str, float] = {
    "m1vert": 0.3,     # mm
    "m2horz": 0.5,     # mm
    "monvtra": 0.1,    # mm
    "monhtra": 0.1,    # mm
    "Bz": 1.0,         # mm
    "Bx": 1.0,         # mm
}


# ---------------------------------------------------------------------------
# Main decision entry point
# ---------------------------------------------------------------------------

def decide_scan_action(
    motor_name: str,
    scan_data: dict,
    iteration: int,
    advisor=None,
    context: Optional[dict] = None,
) -> ScanDecision:
    """Analyze a completed scan and decide what SPEC should do next.

    This is the main entry point called by the FastAPI endpoint
    ``/decide/scan_action``.

    Parameters
    ----------
    motor_name : str
        Which motor was scanned (e.g. "m1vert", "Bz").
    scan_data : dict
        Output from ``spec_reader.get_scan_data()``. Must contain
        'data' (column_name -> np.ndarray), 'scanned_motor', 'command'.
    iteration : int
        Which alignment pass (1 = coarse, 2 = refinement).
    advisor : BeamlineAdvisor, optional
        LLM advisor instance. If None, LLM escalation is skipped.
    context : dict, optional
        Extra context: phase_run_id, experiment info, previous scans.

    Returns
    -------
    ScanDecision
        The decided action including the SPEC command string.
    """
    if context is None:
        context = {}

    strategy = get_strategy(motor_name)
    scan_type = strategy["scan_type"]
    signal_col = strategy["signal"]

    # Extract arrays from scan data
    positions, intensities = _extract_signal(scan_data, motor_name, signal_col)

    if positions is None or intensities is None or len(positions) == 0:
        logger.warning("No data extracted for motor %s", motor_name)
        return ScanDecision(
            action=strategy["fallback"],
            command=strategy["fallback"],
            reason="No scan data available; using fallback",
            confidence=0.0,
            fit_result=None,
        )

    # Run the appropriate fitter
    if scan_type == "aperture":
        threshold = strategy.get("edge_threshold", 0.5)
        fit = fit_aperture_edges(positions, intensities, threshold=threshold)
    elif scan_type == "peak":
        fit = fit_peak(positions, intensities)
    elif scan_type == "edge":
        fit = fit_knife_edge(positions, intensities)
    elif scan_type == "emission":
        fit = fit_emission_peak(positions, intensities)
    else:
        fit = fit_peak(positions, intensities)

    # Check strategy-level thresholds and add issues
    fit = _apply_strategy_checks(fit, strategy, positions)

    # Check which escalation conditions are triggered
    escalation_reasons = _check_escalation(fit, strategy)

    fit_dict = asdict(fit)

    # Determine if escalation to LLM is needed
    if escalation_reasons and advisor is not None:
        return _escalate_to_llm(
            motor_name, scan_data, fit, strategy,
            iteration, advisor, context, escalation_reasons,
        )

    # Clear-cut result -- apply iteration strategy
    if scan_type == "aperture":
        return _decide_aperture(motor_name, fit, strategy, iteration, fit_dict)
    elif scan_type in ("peak", "edge", "emission"):
        return _decide_peak(motor_name, fit, strategy, iteration, fit_dict)
    else:
        return _decide_peak(motor_name, fit, strategy, iteration, fit_dict)


# ---------------------------------------------------------------------------
# Scan-type-specific decision logic
# ---------------------------------------------------------------------------

def _decide_aperture(
    motor: str,
    fit: FitResult,
    strategy: dict,
    iteration: int,
    fit_dict: dict,
) -> ScanDecision:
    """Decision logic for aperture-type scans (m1vert, Bz, Bx)."""
    iter_strategy = strategy.get("iteration_strategy", {})
    preferred = iter_strategy.get(iteration, iter_strategy.get(2, "cen"))

    if not fit.success:
        # Fit failed -- check if we can rescan
        if fit.params.get("found_low") and not fit.params.get("found_high"):
            # Only low edge found: rescan shifted toward high side
            low_edge = fit.params["low_edge"]
            rescan_cmd = _build_rescan_toward_high(motor, low_edge)
            return ScanDecision(
                action="rescan", command=rescan_cmd,
                reason=f"Only low edge found at {low_edge:.3f}; rescanning toward high side",
                confidence=0.3, fit_result=fit_dict,
            )
        elif fit.params.get("found_high") and not fit.params.get("found_low"):
            # Only high edge found: rescan shifted toward low side
            high_edge = fit.params["high_edge"]
            rescan_cmd = _build_rescan_toward_low(motor, high_edge)
            return ScanDecision(
                action="rescan", command=rescan_cmd,
                reason=f"Only high edge found at {high_edge:.3f}; rescanning toward low side",
                confidence=0.3, fit_result=fit_dict,
            )
        else:
            # Complete failure -- use fallback
            return ScanDecision(
                action=strategy["fallback"],
                command=strategy["fallback"],
                reason="Aperture edge detection failed; using fallback",
                confidence=0.1, fit_result=fit_dict,
            )

    # Both edges found
    center = fit.params["center"]

    if preferred == "move_to_center":
        command = _format_spec_command("move", motor, position=center)
        return ScanDecision(
            action="move", command=command,
            reason=f"Aperture center at {center:.4f} (width {fit.params['width']:.3f}mm)",
            confidence=fit.confidence, fit_result=fit_dict,
        )
    elif preferred == "cen":
        return ScanDecision(
            action="cen", command="cen",
            reason=f"Iteration {iteration}: using cen for refinement (center ~{center:.4f})",
            confidence=fit.confidence, fit_result=fit_dict,
        )
    else:
        command = _format_spec_command("move", motor, position=center)
        return ScanDecision(
            action="move", command=command,
            reason=f"Moving to aperture center {center:.4f}",
            confidence=fit.confidence, fit_result=fit_dict,
        )


def _decide_peak(
    motor: str,
    fit: FitResult,
    strategy: dict,
    iteration: int,
    fit_dict: dict,
) -> ScanDecision:
    """Decision logic for peak-type scans (m2horz, slits, Sz, emission)."""
    iter_strategy = strategy.get("iteration_strategy", {})
    preferred = iter_strategy.get(iteration, iter_strategy.get(2, "cen"))

    if not fit.success:
        # Fit failed -- use fallback
        # If we have at least a centroid, try using that
        centroid = fit.params.get("centroid")
        if centroid is not None:
            command = _format_spec_command("move", motor, position=centroid)
            return ScanDecision(
                action="move", command=command,
                reason=f"Fit failed but centroid at {centroid:.4f}; moving there",
                confidence=0.2, fit_result=fit_dict,
            )
        return ScanDecision(
            action=strategy["fallback"],
            command=strategy["fallback"],
            reason="Peak fit failed; using fallback",
            confidence=0.1, fit_result=fit_dict,
        )

    peak_pos = fit.params.get("peak_pos") or fit.params.get("peak_energy")

    if preferred == "peak":
        return ScanDecision(
            action="peak", command="peak",
            reason=f"Iteration {iteration}: using SPEC peak (fitted pos ~{peak_pos:.4f})",
            confidence=fit.confidence, fit_result=fit_dict,
        )
    elif preferred == "cen":
        return ScanDecision(
            action="cen", command="cen",
            reason=f"Iteration {iteration}: using cen for refinement (peak ~{peak_pos:.4f})",
            confidence=fit.confidence, fit_result=fit_dict,
        )
    elif preferred == "move_to_center":
        command = _format_spec_command("move", motor, position=peak_pos)
        return ScanDecision(
            action="move", command=command,
            reason=f"Moving to fitted peak at {peak_pos:.4f}",
            confidence=fit.confidence, fit_result=fit_dict,
        )
    else:
        # Default: use peak on iter 1, cen on iter 2+
        if iteration <= 1:
            return ScanDecision(
                action="peak", command="peak",
                reason=f"Default: peak on iteration {iteration}",
                confidence=fit.confidence, fit_result=fit_dict,
            )
        else:
            return ScanDecision(
                action="cen", command="cen",
                reason=f"Default: cen on iteration {iteration}",
                confidence=fit.confidence, fit_result=fit_dict,
            )


# ---------------------------------------------------------------------------
# LLM escalation
# ---------------------------------------------------------------------------

def _escalate_to_llm(
    motor: str,
    scan_data: dict,
    fit: FitResult,
    strategy: dict,
    iteration: int,
    advisor,
    context: dict,
    escalation_reasons: list[str],
) -> ScanDecision:
    """Consult the LLM advisor for an ambiguous scan result.

    Builds the context packet expected by advisor.decide_scan_action()
    and translates the LLM response into a ScanDecision.
    """
    fit_dict = asdict(fit)

    # Build the scan_data payload for the advisor
    advisor_scan_data = {
        "motor": motor,
        "scan_command": scan_data.get("command", ""),
        "n_points": scan_data.get("n_points", 0),
    }
    # Add scan range from the data
    data_cols = scan_data.get("data", {})
    scanned_motor = scan_data.get("scanned_motor", motor)
    if scanned_motor in data_cols:
        positions = data_cols[scanned_motor]
        advisor_scan_data["scan_range"] = [float(np.min(positions)), float(np.max(positions))]
        advisor_scan_data["positions"] = positions.tolist()
    signal_col = strategy.get("signal", "I0")
    if signal_col in data_cols:
        advisor_scan_data["intensities"] = data_cols[signal_col].tolist()

    # Build context for the advisor
    advisor_context = {
        "iteration": iteration,
        "phase": context.get("phase", "bl_align"),
        "escalation_reason": ", ".join(escalation_reasons),
        "previous_scans": context.get("previous_scans", []),
    }

    # Get the plot image path if available
    plot_path = context.get("plot_image_path")

    try:
        llm_result = advisor.decide_scan_action(
            scan_data=advisor_scan_data,
            fit_result=fit_dict,
            strategy=strategy,
            context=advisor_context,
            plot_image_path=plot_path,
        )

        action = llm_result.get("action", strategy["fallback"])
        command = llm_result.get("command", "")
        reason = llm_result.get("reason", "LLM recommendation")
        confidence = float(llm_result.get("confidence", 0.5))

        # If LLM returned a "move" action without a command, format it
        if action == "move" and not command:
            command = strategy["fallback"]
            action = strategy["fallback"]

        # If command is empty for non-move actions, use the action name
        if not command and action in ("peak", "cen", "accept"):
            command = action if action != "accept" else ""

        return ScanDecision(
            action=action,
            command=command,
            reason=f"[LLM] {reason}",
            confidence=confidence,
            llm_consulted=True,
            fit_result=fit_dict,
        )

    except Exception:
        logger.exception("LLM escalation failed; using fallback")
        return ScanDecision(
            action=strategy["fallback"],
            command=strategy["fallback"],
            reason=f"LLM escalation failed ({', '.join(escalation_reasons)}); using fallback",
            confidence=0.2,
            llm_consulted=True,
            fit_result=fit_dict,
        )


# ---------------------------------------------------------------------------
# Higher-level decision functions (called by server endpoints)
# ---------------------------------------------------------------------------

def decide_need_iteration(scan_records: list[dict], iteration: int) -> str:
    """Decide whether another alignment iteration is needed.

    Called by the ``/decide/need_iteration`` endpoint after completing
    one pass through all alignment motors.

    Parameters
    ----------
    scan_records : list[dict]
        List of scan decision records from the current iteration,
        each containing at minimum 'motor_name' and either
        'result_position' and 'original_position', or 'move_distance'.
    iteration : int
        Which iteration just completed (1 or 2).

    Returns
    -------
    str
        ``"done"`` if alignment has converged, ``"continue"`` if
        another pass is needed.
    """
    # On iteration 1, always do iteration 2 for refinement
    if iteration == 1:
        return "continue"

    # On iteration 2+, check if any motor moved significantly
    for record in scan_records:
        motor = record.get("motor_name", "")
        threshold = _ITERATION_MOVE_THRESHOLDS.get(motor, 0.5)

        # Try to compute move distance from positions
        move_distance = record.get("move_distance")
        if move_distance is None:
            original = record.get("original_position")
            result = record.get("result_position")
            if original is not None and result is not None:
                move_distance = abs(result - original)

        if move_distance is not None and move_distance > threshold:
            logger.info(
                "Motor %s moved %.3f (threshold %.3f); continuing iteration",
                motor, move_distance, threshold,
            )
            return "continue"

        # Check for anomalies
        if record.get("anomaly"):
            logger.info("Anomaly on motor %s; continuing iteration", motor)
            return "continue"

    return "done"


def decide_survey_peaks(
    scan_data: dict, n_expected: int
) -> str:
    """Analyze a wide Sz survey scan to find sample positions.

    Called by the ``/decide/survey_peaks`` endpoint.

    Parameters
    ----------
    scan_data : dict
        Output from ``spec_reader.get_scan_data()``.
    n_expected : int
        Number of samples expected on the holder.

    Returns
    -------
    str
        Space-separated string: ``"N pos1 pos2 ... posN"`` where N is
        the number of peaks found and pos values are Sz positions.
        SPEC parses this with sscanf.
    """
    positions, intensities = _extract_signal(scan_data, "Sz", "vortDT")

    if positions is None or len(positions) == 0:
        # Try I0 as fallback signal
        positions, intensities = _extract_signal(scan_data, "Sz", "I0")

    if positions is None or len(positions) == 0:
        return "0"

    fit = detect_peaks_survey(positions, intensities, n_expected)

    if not fit.success or fit.params.get("n_found", 0) == 0:
        return "0"

    peak_positions = fit.params["peak_positions"]
    n_found = fit.params["n_found"]

    # Format: "N pos1 pos2 ... posN"
    parts = [str(n_found)]
    parts.extend(f"{p:.4f}" for p in peak_positions)
    return " ".join(parts)


def decide_sample_boundary(scan_data: dict, sample_num: int) -> str:
    """Analyze a d2scan to find Sx/Sy sample boundaries.

    Called by the ``/decide/sample_boundary`` endpoint.

    Parameters
    ----------
    scan_data : dict
        Output from ``spec_reader.get_scan_data()`` for a d2scan
        of Sx and Sy.
    sample_num : int
        Which sample number (for logging).

    Returns
    -------
    str
        ``"sx_lo sx_hi sy_lo sy_hi"`` if boundaries found, or a
        rescan command string if the scan needs to be repeated.
    """
    data = scan_data.get("data", {})
    signal_col = "vortDT"
    if signal_col not in data:
        # Try other counters
        for col in ["I0", "I1"]:
            if col in data:
                signal_col = col
                break

    if signal_col not in data:
        return f"dscan Sx -5 5 Sy -5 5 50 0.2"

    intensities = data[signal_col]

    # For a d2scan, both Sx and Sy are scanned simultaneously
    sx = data.get("Sx")
    sy = data.get("Sy")

    if sx is None or sy is None:
        # Try scanned_motor from the command
        return f"dscan Sx -5 5 Sy -5 5 50 0.2"

    # Find boundaries: where signal rises above threshold
    sig_min = np.min(intensities)
    sig_max = np.max(intensities)
    sig_range = sig_max - sig_min

    if sig_range < 1.0:
        return f"dscan Sx -5 5 Sy -5 5 50 0.2"

    threshold = sig_min + 0.2 * sig_range
    above = intensities > threshold

    if not np.any(above):
        return f"dscan Sx -5 5 Sy -5 5 50 0.2"

    sx_above = sx[above]
    sy_above = sy[above]

    sx_lo = float(np.min(sx_above))
    sx_hi = float(np.max(sx_above))
    sy_lo = float(np.min(sy_above))
    sy_hi = float(np.max(sy_above))

    return f"{sx_lo:.4f} {sx_hi:.4f} {sy_lo:.4f} {sy_hi:.4f}"


def decide_emission_peak(scan_data: dict) -> str:
    """Analyze an emission scan to find the HERFD energy.

    Called by the ``/decide/emission_peak`` endpoint.

    Parameters
    ----------
    scan_data : dict
        Output from ``spec_reader.get_scan_data()``.

    Returns
    -------
    str
        Fitted peak energy as a string (e.g. ``"6404.2"``), or
        ``"fallback"`` if fitting fails.
    """
    # The scanned motor for emission scans is typically 'emiss'
    scanned = scan_data.get("scanned_motor", "emiss")
    positions, intensities = _extract_signal(scan_data, scanned, "vortDT")

    if positions is None or len(positions) == 0:
        positions, intensities = _extract_signal(scan_data, scanned, "I0")

    if positions is None or len(positions) == 0:
        return "fallback"

    fit = fit_emission_peak(positions, intensities)

    if fit.success and fit.params.get("peak_energy") is not None:
        return f"{fit.params['peak_energy']:.2f}"

    # Fall back to raw maximum
    if fit.params.get("peak_energy") is not None:
        return f"{fit.params['peak_energy']:.2f}"

    return "fallback"


# ---------------------------------------------------------------------------
# Escalation check
# ---------------------------------------------------------------------------

def _check_escalation(fit: FitResult, strategy: dict) -> list[str]:
    """Check which escalation conditions are triggered.

    Compares the fit result's issues and statistics against the
    strategy's ``escalate_to_llm_when`` list.

    Parameters
    ----------
    fit : FitResult
        The completed fit result.
    strategy : dict
        Motor strategy with escalation conditions.

    Returns
    -------
    list[str]
        Names of triggered escalation conditions (empty if none).
    """
    escalate_conditions = strategy.get("escalate_to_llm_when", [])
    triggered = []

    for condition in escalate_conditions:
        # Direct match against fit issues
        if condition in fit.issues:
            triggered.append(condition)
            continue

        # Check composite conditions
        if condition == "fwhm_outside_range":
            fwhm = fit.params.get("fwhm") or fit.params.get("width") or fit.params.get("fwhm_eV")
            if fwhm is not None:
                fwhm_range = strategy.get("typical_fwhm", (0, float("inf")))
                if fwhm < fwhm_range[0] or fwhm > fwhm_range[1]:
                    triggered.append(condition)

        elif condition == "peak_counts_below_minimum":
            peak_val = fit.params.get("peak_intensity") or fit.params.get("peak_height")
            min_counts = strategy.get("min_peak_counts", 0)
            if peak_val is not None and peak_val < min_counts:
                triggered.append(condition)

        elif condition == "fit_quality_below_0.8":
            if fit.confidence < 0.8:
                triggered.append(condition)

        elif condition == "multiple_peaks_detected":
            if "multiple_peaks" in fit.issues:
                triggered.append(condition)

        elif condition == "large_move":
            # This is checked externally (the caller knows the current position)
            # We flag it here if the center is far from the scan midpoint
            center = fit.params.get("center")
            if center is not None and "low_edge" in fit.params and "high_edge" in fit.params:
                low = fit.params.get("low_edge")
                high = fit.params.get("high_edge")
                if low is not None and high is not None:
                    midpoint = (low + high) / 2.0
                    # "large_move" is context-dependent; skip here
                    pass

    return triggered


# ---------------------------------------------------------------------------
# Strategy-level checks
# ---------------------------------------------------------------------------

def _apply_strategy_checks(
    fit: FitResult, strategy: dict, positions: np.ndarray
) -> FitResult:
    """Apply strategy-level threshold checks and augment fit issues.

    Checks peak counts and FWHM against the strategy thresholds
    and adds issues that the fitter itself does not know about.
    """
    # Check minimum peak counts
    peak_val = fit.params.get("peak_intensity") or fit.params.get("peak_height")
    min_counts = strategy.get("min_peak_counts", 0)
    if peak_val is not None and peak_val < min_counts:
        if "peak_counts_below_minimum" not in fit.issues:
            fit.issues.append("peak_counts_below_minimum")

    # Check FWHM range
    fwhm = fit.params.get("fwhm") or fit.params.get("width") or fit.params.get("fwhm_eV")
    fwhm_range = strategy.get("typical_fwhm")
    if fwhm is not None and fwhm_range is not None:
        if fwhm < fwhm_range[0] or fwhm > fwhm_range[1]:
            if "fwhm_outside_range" not in fit.issues:
                fit.issues.append("fwhm_outside_range")

    return fit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_signal(
    scan_data: dict, motor_name: str, signal_col: str
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Extract position and signal arrays from scan_data.

    Parameters
    ----------
    scan_data : dict
        Output from spec_reader.get_scan_data().
    motor_name : str
        Expected motor name for the x-axis.
    signal_col : str
        Counter column name for the y-axis.

    Returns
    -------
    tuple[np.ndarray | None, np.ndarray | None]
        (positions, intensities) or (None, None) if extraction fails.
    """
    data = scan_data.get("data", {})

    # Try the specified motor name first, then the scanned_motor
    scanned = scan_data.get("scanned_motor", motor_name)
    positions = data.get(motor_name)
    if positions is None:
        positions = data.get(scanned)

    # Try the specified signal, then fallback columns
    intensities = data.get(signal_col)
    if intensities is None:
        for fallback in ["I0", "I1", "vortDT"]:
            if fallback in data and fallback != signal_col:
                intensities = data[fallback]
                break

    if positions is None or intensities is None:
        return None, None

    # Ensure numpy arrays
    positions = np.asarray(positions, dtype=float)
    intensities = np.asarray(intensities, dtype=float)

    # Ensure same length
    min_len = min(len(positions), len(intensities))
    if min_len == 0:
        return None, None
    positions = positions[:min_len]
    intensities = intensities[:min_len]

    return positions, intensities


def _format_spec_command(
    action: str,
    motor: str,
    position: Optional[float] = None,
    scan_params: Optional[dict] = None,
) -> str:
    """Format a SPEC command string.

    Parameters
    ----------
    action : str
        One of "move", "peak", "cen", "rescan".
    motor : str
        Motor mnemonic.
    position : float, optional
        Target position for "move" actions.
    scan_params : dict, optional
        For "rescan": keys start, end, npts, time.

    Returns
    -------
    str
        Valid SPEC command string.
    """
    if action == "move" and position is not None:
        return f"umv {motor} {position:.6f}"
    elif action == "peak":
        return "peak"
    elif action == "cen":
        return "cen"
    elif action == "rescan" and scan_params is not None:
        start = scan_params.get("start", -1)
        end = scan_params.get("end", 1)
        npts = scan_params.get("npts", 50)
        time_s = scan_params.get("time", 0.2)
        return f"dscan {motor} {start:.4f} {end:.4f} {npts} {time_s}"
    else:
        return action


def _build_rescan_toward_high(motor: str, low_edge: float) -> str:
    """Build a dscan command that extends the scan range toward the high side.

    Used when only the low edge of an aperture was found, suggesting
    the high edge is beyond the current scan range.
    """
    # Start from near the low edge, scan wider toward high
    start = low_edge - 0.5
    end = low_edge + 3.0  # 50% wider than typical aperture
    # Use relative scan centered roughly around current position
    center = (start + end) / 2.0
    half_range = (end - start) / 2.0
    return f"dscan {motor} {-half_range:.4f} {half_range * 1.5:.4f} 50 0.2"


def _build_rescan_toward_low(motor: str, high_edge: float) -> str:
    """Build a dscan command that extends the scan range toward the low side.

    Used when only the high edge of an aperture was found, suggesting
    the low edge is beyond the current scan range.
    """
    # Start wider toward low, end near the high edge
    end = high_edge + 0.5
    start = high_edge - 3.0
    center = (start + end) / 2.0
    half_range = (end - start) / 2.0
    return f"dscan {motor} {-half_range * 1.5:.4f} {half_range:.4f} 50 0.2"
