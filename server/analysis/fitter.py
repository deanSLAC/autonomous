"""
Deterministic scan analysis for BL15-2 beamline automation.

Pure fitting functions using scipy/numpy. No LLM calls -- just math.
Each function returns a FitResult dataclass with the fit parameters,
a confidence score (0-1), and a list of detected issues.

These functions replace the SPEC-side analysis (find_aperture_edges,
analyze_m1_scan, analyze_m2_scan, etc.) with more robust Python fits.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, savgol_filter
from scipy.special import erf

logger = logging.getLogger(__name__)


@dataclass
class FitResult:
    """Result from a scan fitting function.

    Attributes
    ----------
    success : bool
        Whether the fit converged and produced a usable result.
    confidence : float
        Quality score from 0 (useless) to 1 (excellent).
    params : dict
        Fit-specific parameters (peak_pos, fwhm, edges, etc.).
    issues : list[str]
        Problem names matching ``escalate_to_llm_when`` keys in
        scan_strategies.py (e.g. "only_one_edge_found",
        "peak_at_scan_boundary").
    """

    success: bool
    confidence: float
    params: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_input(positions: np.ndarray, intensities: np.ndarray,
                    min_points: int = 5) -> list[str]:
    """Check for degenerate input data. Returns a list of issue strings."""
    issues = []
    if positions is None or intensities is None:
        issues.append("null_data")
        return issues
    if len(positions) == 0 or len(intensities) == 0:
        issues.append("empty_data")
        return issues
    if len(positions) != len(intensities):
        issues.append("length_mismatch")
        return issues
    if len(positions) < min_points:
        issues.append("too_few_points")
    if np.all(intensities == intensities[0]):
        issues.append("constant_signal")
    if np.all(intensities == 0):
        issues.append("zero_signal")
    if np.any(np.isnan(positions)) or np.any(np.isnan(intensities)):
        issues.append("nan_in_data")
    return issues


def _compute_r_squared(y_data: np.ndarray, y_fit: np.ndarray) -> float:
    """Compute R-squared goodness-of-fit metric."""
    ss_res = np.sum((y_data - y_fit) ** 2)
    ss_tot = np.sum((y_data - np.mean(y_data)) ** 2)
    if ss_tot == 0:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


# ---------------------------------------------------------------------------
# Model functions
# ---------------------------------------------------------------------------

def _gaussian(x, amplitude, center, sigma, baseline):
    """Gaussian peak model."""
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2) + baseline


def _erf_step(x, amplitude, center, sigma, baseline):
    """Error function step (for knife-edge profiles)."""
    return amplitude * 0.5 * (1.0 + erf((x - center) / (sigma * np.sqrt(2)))) + baseline


def _pseudo_voigt(x, amplitude, center, sigma, eta, baseline):
    """Pseudo-Voigt profile: weighted sum of Gaussian and Lorentzian.

    Parameters
    ----------
    eta : float
        Lorentzian fraction (0 = pure Gaussian, 1 = pure Lorentzian).
    """
    gauss = np.exp(-0.5 * ((x - center) / sigma) ** 2)
    lorentz = 1.0 / (1.0 + ((x - center) / sigma) ** 2)
    return amplitude * (eta * lorentz + (1.0 - eta) * gauss) + baseline


# ---------------------------------------------------------------------------
# Public fitting functions
# ---------------------------------------------------------------------------

def fit_aperture_edges(positions: np.ndarray, intensities: np.ndarray,
                       threshold: float = 0.5) -> FitResult:
    """Find rising/falling edges in a flat-top aperture scan.

    Used for m1vert, Bz, and Bx scans where the beam passes through
    an aperture producing a profile with sharp edges and a flat top.

    The algorithm normalizes the signal to 0-1, then scans for
    threshold crossings with sub-point linear interpolation.

    Parameters
    ----------
    positions : np.ndarray
        Motor positions from the scan.
    intensities : np.ndarray
        Signal values (I0 for m1, I1 for B-stage).
    threshold : float
        Normalized intensity threshold for edge detection (0-1).

    Returns
    -------
    FitResult
        params keys: low_edge, high_edge, center, width,
        peak_intensity, found_low, found_high.
    """
    issues = _validate_input(positions, intensities)
    if "empty_data" in issues or "null_data" in issues:
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Sort by position
    sort_idx = np.argsort(positions)
    pos = positions[sort_idx].astype(float)
    sig = intensities[sort_idx].astype(float)

    # Basic signal statistics
    sig_min = np.min(sig)
    sig_max = np.max(sig)
    sig_range = sig_max - sig_min
    peak_intensity = float(sig_max)

    if sig_range < 1.0:
        issues.append("low_signal")
        return FitResult(
            success=False, confidence=0.0,
            params={"peak_intensity": peak_intensity,
                    "found_low": False, "found_high": False},
            issues=issues,
        )

    # Normalize to 0-1
    norm = (sig - sig_min) / sig_range

    # Find threshold crossings with linear interpolation
    low_edge = None
    high_edge = None

    for i in range(1, len(norm)):
        # Rising edge (entering aperture)
        if low_edge is None and norm[i - 1] < threshold <= norm[i]:
            # Linear interpolation for sub-point precision
            frac = (threshold - norm[i - 1]) / (norm[i] - norm[i - 1])
            low_edge = pos[i - 1] + frac * (pos[i] - pos[i - 1])

        # Falling edge (exiting aperture) -- only after finding low edge
        elif low_edge is not None and high_edge is None and norm[i - 1] >= threshold > norm[i]:
            frac = (threshold - norm[i]) / (norm[i - 1] - norm[i])
            high_edge = pos[i] - frac * (pos[i] - pos[i - 1])

    found_low = low_edge is not None
    found_high = high_edge is not None

    # Handle case where we start above threshold (no rising edge)
    if not found_low and norm[0] >= threshold:
        # Scan started inside the aperture -- low edge is at or before scan start
        issues.append("low_edge_at_boundary")
        # Check if there is a falling edge
        if not found_high:
            for i in range(1, len(norm)):
                if norm[i - 1] >= threshold > norm[i]:
                    frac = (threshold - norm[i]) / (norm[i - 1] - norm[i])
                    high_edge = pos[i] - frac * (pos[i] - pos[i - 1])
                    found_high = True
                    break

    # Handle case where we end above threshold (no falling edge)
    if found_low and not found_high and norm[-1] >= threshold:
        issues.append("high_edge_at_boundary")

    # Determine if only one edge was found
    if found_low and not found_high:
        issues.append("only_one_edge_found")
    elif not found_low and found_high:
        issues.append("only_one_edge_found")
    elif not found_low and not found_high:
        issues.append("no_edges_found")

    # Compute center and width if both edges found
    center = None
    width = None
    if found_low and found_high:
        center = (low_edge + high_edge) / 2.0
        width = high_edge - low_edge

    # Check if peak is at scan boundary (first or last 10% of range)
    scan_range = pos[-1] - pos[0]
    peak_idx = np.argmax(sig)
    peak_pos = pos[peak_idx]
    boundary_zone = 0.1 * scan_range
    if peak_pos - pos[0] < boundary_zone or pos[-1] - peak_pos < boundary_zone:
        issues.append("peak_at_boundary")

    # Compute confidence
    confidence = 0.0
    if found_low and found_high:
        # High confidence if both edges found and profile looks clean
        flat_region = norm[(norm > threshold)]
        if len(flat_region) > 3:
            flatness = 1.0 - np.std(flat_region) / np.mean(flat_region)
            confidence = max(0.0, min(1.0, flatness))
        else:
            confidence = 0.6
    elif found_low or found_high:
        confidence = 0.3
    else:
        confidence = 0.0

    params = {
        "low_edge": float(low_edge) if low_edge is not None else None,
        "high_edge": float(high_edge) if high_edge is not None else None,
        "center": float(center) if center is not None else None,
        "width": float(width) if width is not None else None,
        "peak_intensity": peak_intensity,
        "found_low": found_low,
        "found_high": found_high,
    }

    return FitResult(
        success=found_low and found_high,
        confidence=confidence,
        params=params,
        issues=issues,
    )


def fit_peak(positions: np.ndarray, intensities: np.ndarray) -> FitResult:
    """Fit a Gaussian peak to scan data.

    Used for m2horz, monvtra, monhtra, and sample Sz scans where
    the signal has a single peak profile.

    Parameters
    ----------
    positions : np.ndarray
        Motor positions from the scan.
    intensities : np.ndarray
        Signal values.

    Returns
    -------
    FitResult
        params keys: peak_pos, peak_height, fwhm, centroid, sigma,
        baseline, fit_r_squared.
    """
    issues = _validate_input(positions, intensities)
    if "empty_data" in issues or "null_data" in issues:
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Sort by position
    sort_idx = np.argsort(positions)
    pos = positions[sort_idx].astype(float)
    sig = intensities[sort_idx].astype(float)

    sig_min = np.min(sig)
    sig_max = np.max(sig)
    sig_range = sig_max - sig_min

    if sig_range < 1.0:
        issues.append("low_signal")
        return FitResult(success=False, confidence=0.0,
                         params={"peak_height": float(sig_max)}, issues=issues)

    # Compute centroid (center of mass) as a robust initial estimate
    sig_bg = sig - sig_min
    total = np.sum(sig_bg)
    if total > 0:
        centroid = float(np.sum(pos * sig_bg) / total)
    else:
        centroid = float(np.mean(pos))

    # Check for peak at scan boundary
    scan_range = pos[-1] - pos[0]
    peak_idx = np.argmax(sig)
    peak_pos_raw = float(pos[peak_idx])
    boundary_zone = 0.1 * scan_range

    if peak_pos_raw - pos[0] < boundary_zone:
        issues.append("peak_at_scan_boundary")
    if pos[-1] - peak_pos_raw < boundary_zone:
        issues.append("peak_at_scan_boundary")

    # Check for multiple peaks
    try:
        # Smooth signal to avoid noise peaks
        if len(sig) > 7:
            window = min(7, len(sig) - (1 if len(sig) % 2 == 0 else 0))
            if window >= 3:
                smoothed = savgol_filter(sig, window, min(2, window - 1))
            else:
                smoothed = sig
        else:
            smoothed = sig

        min_distance = max(3, len(sig) // 10)
        prominence = 0.2 * sig_range
        peaks_found, properties = find_peaks(
            smoothed, distance=min_distance, prominence=prominence
        )
        if len(peaks_found) > 1:
            issues.append("multiple_peaks")
    except Exception:
        pass

    # Gaussian fit via curve_fit
    # Initial guesses
    p0 = [float(sig_range), centroid, float(scan_range / 6.0), float(sig_min)]

    # Bounds: amplitude > 0, center within scan range, sigma > 0, baseline >= 0
    bounds_lo = [0, pos[0] - scan_range, scan_range * 0.001, -abs(sig_max)]
    bounds_hi = [sig_range * 3, pos[-1] + scan_range, scan_range * 2, sig_max * 2]

    try:
        popt, pcov = curve_fit(
            _gaussian, pos, sig, p0=p0,
            bounds=(bounds_lo, bounds_hi),
            maxfev=5000,
        )
        amplitude, center, sigma, baseline = popt

        # Compute fit quality
        y_fit = _gaussian(pos, *popt)
        r_squared = _compute_r_squared(sig, y_fit)

        peak_pos = float(center)
        peak_height = float(amplitude + baseline)
        fwhm = float(2.355 * abs(sigma))

        if r_squared < 0.5:
            issues.append("poor_fit")

        # Confidence based on R-squared and signal quality
        confidence = r_squared * 0.8
        if "peak_at_scan_boundary" not in issues:
            confidence += 0.1
        if "multiple_peaks" not in issues:
            confidence += 0.1
        confidence = min(1.0, confidence)

        params = {
            "peak_pos": peak_pos,
            "peak_height": peak_height,
            "fwhm": fwhm,
            "centroid": centroid,
            "sigma": float(abs(sigma)),
            "baseline": float(baseline),
            "fit_r_squared": float(r_squared),
        }

        return FitResult(
            success=True, confidence=confidence, params=params, issues=issues
        )

    except (RuntimeError, ValueError) as exc:
        logger.debug("Gaussian fit failed: %s", exc)
        issues.append("poor_fit")

        # Fall back to centroid-based result
        params = {
            "peak_pos": centroid,
            "peak_height": float(sig_max),
            "fwhm": None,
            "centroid": centroid,
            "sigma": None,
            "baseline": float(sig_min),
            "fit_r_squared": 0.0,
        }

        return FitResult(
            success=False, confidence=0.2, params=params, issues=issues
        )


def fit_knife_edge(positions: np.ndarray, intensities: np.ndarray) -> FitResult:
    """Fit error function to knife-edge beam profile.

    Used for beam size measurement (beamx, beamz). The beam profile
    through a knife edge produces an erf step function. The FWHM of
    the underlying Gaussian beam is extracted from the erf sigma.

    Model: y = A * (1 + erf((x - center) / (sigma * sqrt(2)))) / 2 + B

    Parameters
    ----------
    positions : np.ndarray
        Motor positions (in mm, converted to um for FWHM output).
    intensities : np.ndarray
        Signal values.

    Returns
    -------
    FitResult
        params keys: center, fwhm_um, sigma, amplitude, baseline,
        fit_r_squared.
    """
    issues = _validate_input(positions, intensities)
    if "empty_data" in issues or "null_data" in issues:
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Sort by position
    sort_idx = np.argsort(positions)
    pos = positions[sort_idx].astype(float)
    sig = intensities[sort_idx].astype(float)

    sig_min = np.min(sig)
    sig_max = np.max(sig)
    sig_range = sig_max - sig_min

    if sig_range < 1.0:
        issues.append("low_signal")
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Determine if step is rising or falling
    left_mean = np.mean(sig[:max(1, len(sig) // 4)])
    right_mean = np.mean(sig[-(len(sig) // 4):])
    rising = right_mean > left_mean

    # For a falling step, flip the data for fitting, then adjust
    if not rising:
        sig_fit = -sig
        amplitude_sign = -1.0
    else:
        sig_fit = sig
        amplitude_sign = 1.0

    # Normalize for fitting
    fit_min = np.min(sig_fit)
    fit_max = np.max(sig_fit)
    fit_range = fit_max - fit_min

    # Initial guesses
    scan_range = pos[-1] - pos[0]
    center_guess = float(pos[np.argmin(np.abs(sig_fit - (fit_min + fit_range / 2)))])
    sigma_guess = float(scan_range / 10.0)

    p0 = [float(fit_range), center_guess, sigma_guess, float(fit_min)]
    bounds_lo = [0, pos[0] - scan_range, scan_range * 0.0001, fit_min - abs(fit_range)]
    bounds_hi = [fit_range * 3, pos[-1] + scan_range, scan_range, fit_max + abs(fit_range)]

    try:
        popt, pcov = curve_fit(
            _erf_step, pos, sig_fit, p0=p0,
            bounds=(bounds_lo, bounds_hi),
            maxfev=5000,
        )
        amplitude, center, sigma, baseline = popt

        y_fit = _erf_step(pos, *popt)
        r_squared = _compute_r_squared(sig_fit, y_fit)

        # FWHM of the underlying Gaussian beam in um
        # positions are in mm, so multiply by 1000
        fwhm_um = float(2.355 * abs(sigma) * 1000.0)

        if r_squared < 0.7:
            issues.append("poor_fit")

        # Check for asymmetry: compare residuals on each side of center
        left_mask = pos < center
        right_mask = pos >= center
        if np.sum(left_mask) > 2 and np.sum(right_mask) > 2:
            left_resid = np.mean(np.abs(sig_fit[left_mask] - y_fit[left_mask]))
            right_resid = np.mean(np.abs(sig_fit[right_mask] - y_fit[right_mask]))
            asymmetry = abs(left_resid - right_resid) / max(left_resid, right_resid, 1e-10)
            if asymmetry > 0.5:
                issues.append("asymmetric_profile")

        confidence = r_squared * 0.9
        if "asymmetric_profile" not in issues:
            confidence += 0.1
        confidence = min(1.0, confidence)

        params = {
            "center": float(center),
            "fwhm_um": fwhm_um,
            "sigma": float(abs(sigma)),
            "amplitude": float(amplitude * amplitude_sign),
            "baseline": float(baseline * amplitude_sign) if not rising else float(baseline),
            "fit_r_squared": float(r_squared),
        }

        return FitResult(
            success=True, confidence=confidence, params=params, issues=issues
        )

    except (RuntimeError, ValueError) as exc:
        logger.debug("Erf fit failed: %s", exc)
        issues.append("poor_fit")
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)


def detect_peaks_survey(positions: np.ndarray, intensities: np.ndarray,
                        n_expected: int, threshold_frac: float = 0.1) -> FitResult:
    """Find sample peaks in a wide Sz survey scan.

    Used during sample alignment to locate individual samples on
    a sample holder. Peaks above ``threshold_frac`` of the signal
    range are detected using scipy.signal.find_peaks.

    Parameters
    ----------
    positions : np.ndarray
        Motor positions (Sz).
    intensities : np.ndarray
        Signal values (typically vortDT fluorescence).
    n_expected : int
        Number of samples expected on the holder.
    threshold_frac : float
        Minimum peak height as a fraction of (max - min) range.

    Returns
    -------
    FitResult
        params keys: peak_positions (list[float]), n_found (int),
        peak_heights (list[float]).
    """
    issues = _validate_input(positions, intensities)
    if "empty_data" in issues or "null_data" in issues:
        return FitResult(success=False, confidence=0.0,
                         params={"peak_positions": [], "n_found": 0, "peak_heights": []},
                         issues=issues)

    # Sort by position
    sort_idx = np.argsort(positions)
    pos = positions[sort_idx].astype(float)
    sig = intensities[sort_idx].astype(float)

    sig_min = np.min(sig)
    sig_max = np.max(sig)
    sig_range = sig_max - sig_min

    if sig_range < 1.0:
        issues.append("low_signal")
        return FitResult(
            success=False, confidence=0.0,
            params={"peak_positions": [], "n_found": 0, "peak_heights": []},
            issues=issues,
        )

    # Height threshold
    height_threshold = sig_min + threshold_frac * sig_range

    # Minimum distance between peaks: total range / (2 * expected peaks)
    scan_pts = len(pos)
    if n_expected > 0:
        min_distance = max(3, scan_pts // (2 * n_expected))
    else:
        min_distance = max(3, scan_pts // 10)

    # Smooth signal before peak detection
    if scan_pts > 7:
        window = min(7, scan_pts - (1 if scan_pts % 2 == 0 else 0))
        if window >= 3:
            smoothed = savgol_filter(sig, window, min(2, window - 1))
        else:
            smoothed = sig
    else:
        smoothed = sig

    # Find peaks
    peak_indices, properties = find_peaks(
        smoothed,
        height=height_threshold,
        distance=min_distance,
        prominence=0.05 * sig_range,
    )

    peak_positions = [float(pos[i]) for i in peak_indices]
    peak_heights = [float(sig[i]) for i in peak_indices]
    n_found = len(peak_positions)

    # Check issues
    if n_found < n_expected:
        issues.append("fewer_peaks_than_expected")
    if n_found > n_expected:
        issues.append("more_peaks_than_expected")

    # Check for very close peaks
    if n_found > 1:
        spacings = np.diff(peak_positions)
        scan_range = pos[-1] - pos[0]
        if np.min(spacings) < 0.05 * scan_range:
            issues.append("peaks_very_close")

    # Confidence
    if n_found == n_expected and n_expected > 0:
        confidence = 0.9
    elif n_found > 0:
        ratio = min(n_found, n_expected) / max(n_found, n_expected, 1)
        confidence = 0.5 * ratio
    else:
        confidence = 0.0

    params = {
        "peak_positions": peak_positions,
        "n_found": n_found,
        "peak_heights": peak_heights,
    }

    return FitResult(
        success=n_found > 0,
        confidence=confidence,
        params=params,
        issues=issues,
    )


def fit_emission_peak(energies: np.ndarray, intensities: np.ndarray) -> FitResult:
    """Fit pseudo-Voigt to an emission line for HERFD energy determination.

    Emission lines are slightly asymmetric. We use a pseudo-Voigt
    profile (sum of Gaussian + Lorentzian weighted by eta) to capture
    this shape.

    Parameters
    ----------
    energies : np.ndarray
        Emission energy values (eV).
    intensities : np.ndarray
        Signal values (typically vortDT).

    Returns
    -------
    FitResult
        params keys: peak_energy, fwhm_eV, peak_height, eta
        (Lorentzian fraction), fit_r_squared.
    """
    issues = _validate_input(energies, intensities)
    if "empty_data" in issues or "null_data" in issues:
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Sort by energy
    sort_idx = np.argsort(energies)
    en = energies[sort_idx].astype(float)
    sig = intensities[sort_idx].astype(float)

    sig_min = np.min(sig)
    sig_max = np.max(sig)
    sig_range = sig_max - sig_min

    if sig_range < 1.0:
        issues.append("low_signal")
        return FitResult(success=False, confidence=0.0, params={}, issues=issues)

    # Initial guesses
    peak_idx = np.argmax(sig)
    center_guess = float(en[peak_idx])
    en_range = en[-1] - en[0]
    sigma_guess = float(en_range / 20.0)

    p0 = [float(sig_range), center_guess, sigma_guess, 0.3, float(sig_min)]
    bounds_lo = [0, en[0], en_range * 0.001, 0.0, -abs(sig_max)]
    bounds_hi = [sig_range * 3, en[-1], en_range, 1.0, sig_max * 2]

    try:
        popt, pcov = curve_fit(
            _pseudo_voigt, en, sig, p0=p0,
            bounds=(bounds_lo, bounds_hi),
            maxfev=5000,
        )
        amplitude, center, sigma, eta, baseline = popt

        y_fit = _pseudo_voigt(en, *popt)
        r_squared = _compute_r_squared(sig, y_fit)

        # FWHM depends on eta: approximate as 2*sigma * weighted average
        # For Gaussian: FWHM = 2.355 * sigma
        # For Lorentzian: FWHM = 2 * sigma
        fwhm_eV = float(sigma * (2.355 * (1 - eta) + 2.0 * eta))

        peak_height = float(amplitude + baseline)

        if r_squared < 0.5:
            issues.append("poor_fit")

        # Check for asymmetry via residuals
        left_mask = en < center
        right_mask = en >= center
        if np.sum(left_mask) > 2 and np.sum(right_mask) > 2:
            left_resid = np.mean(np.abs(sig[left_mask] - y_fit[left_mask]))
            right_resid = np.mean(np.abs(sig[right_mask] - y_fit[right_mask]))
            if max(left_resid, right_resid) > 0:
                asymmetry = abs(left_resid - right_resid) / max(left_resid, right_resid)
                if asymmetry > 0.5:
                    issues.append("asymmetric")

        # Check for multiple peaks
        try:
            if len(sig) > 7:
                window = min(7, len(sig) - (1 if len(sig) % 2 == 0 else 0))
                if window >= 3:
                    smoothed = savgol_filter(sig, window, min(2, window - 1))
                else:
                    smoothed = sig
            else:
                smoothed = sig

            min_distance = max(3, len(sig) // 10)
            peaks_found, _ = find_peaks(smoothed, distance=min_distance,
                                        prominence=0.15 * sig_range)
            if len(peaks_found) > 1:
                issues.append("multiple_peaks")
        except Exception:
            pass

        confidence = r_squared * 0.8
        if "asymmetric" not in issues:
            confidence += 0.1
        if "multiple_peaks" not in issues:
            confidence += 0.1
        confidence = min(1.0, confidence)

        params = {
            "peak_energy": float(center),
            "fwhm_eV": fwhm_eV,
            "peak_height": peak_height,
            "eta": float(eta),
            "fit_r_squared": float(r_squared),
        }

        return FitResult(
            success=True, confidence=confidence, params=params, issues=issues
        )

    except (RuntimeError, ValueError) as exc:
        logger.debug("Pseudo-Voigt fit failed: %s", exc)
        issues.append("poor_fit")

        # Fall back to raw peak
        peak_idx = np.argmax(sig)
        params = {
            "peak_energy": float(en[peak_idx]),
            "fwhm_eV": None,
            "peak_height": float(sig_max),
            "eta": None,
            "fit_r_squared": 0.0,
        }

        return FitResult(
            success=False, confidence=0.2, params=params, issues=issues
        )
