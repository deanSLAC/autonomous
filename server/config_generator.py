"""Config generator: reads experiment from DB, writes SPEC .mac file.

Can be called:
  1. Programmatically by the web form submit handler
  2. CLI: python config_generator.py --from-db --experiment-id <id>
  3. CLI: python config_generator.py --from-db  (uses active experiment)
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
import yaml

# Ensure imports work whether run as module or script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.client import (
    get_active_experiment,
    get_elements_for_experiment,
    get_experiment,
    get_samples_for_holder,
)
from db.models import (
    Experiment,
    ExperimentElement,
    SampleHolder,
    SamplePosition,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
# Prefer the project-root config (autonomous/config/defaults.yaml).
_PROJECT_CONFIG = _THIS_DIR.parent / "config" / "defaults.yaml"
_LOCAL_CONFIG = _THIS_DIR / "config" / "defaults.yaml"
_DEFAULTS_PATH = _PROJECT_CONFIG if _PROJECT_CONFIG.exists() else _LOCAL_CONFIG
_MACROS_DIR = _THIS_DIR.parent / "macros"
_SPEC_INSTALL_DIR = Path("/usr/local/lib/spec.d")


def _load_defaults() -> dict:
    """Load defaults.yaml configuration."""
    with open(_DEFAULTS_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def sanitize_spec_string(val: str) -> str:
    """Remove chars that break SPEC: double quotes, single quotes, backslashes."""
    if val is None:
        return ""
    return re.sub(r'[\\"\']', '', str(val))


def _safe_filename(name: str) -> str:
    """Ensure a string is safe for SPEC filenames."""
    return re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_experiment(experiment_id: str) -> list[str]:
    """Validate an experiment's configuration.
    Returns list of error strings (empty = valid).
    """
    errors = []
    defaults = _load_defaults()
    limits = defaults.get("motor_limits", {})

    exp = get_experiment(experiment_id)
    if exp is None:
        return [f"Experiment {experiment_id} not found"]

    if not exp.name or not exp.name.strip():
        errors.append("Experiment name is required")
    elif not re.match(r'^[a-zA-Z0-9_\-. ]+$', exp.name):
        errors.append("Experiment name contains invalid characters")

    if exp.mono_crystal not in ("A", "B"):
        errors.append("Mono crystal must be A or B")

    if exp.beam_size_h not in ("big", "focused"):
        errors.append("Horizontal beam size must be big or focused")

    if exp.beam_size_v not in ("big", "focused"):
        errors.append("Vertical beam size must be big or focused")

    # Elements
    elements = get_elements_for_experiment(experiment_id)
    if not elements:
        errors.append("At least one element must be configured")

    energy_limits = limits.get("energy", [4950, 25000])
    emiss_limits = limits.get("emiss", [2000, 20000])
    element_symbols = set()

    for i, el in enumerate(elements, 1):
        pfx = f"Element {i} ({el.element_symbol})"
        element_symbols.add(el.element_symbol)

        if not el.element_symbol or not el.element_symbol.strip():
            errors.append(f"{pfx}: symbol is required")

        if not (energy_limits[0] <= el.incident_energy_eV <= energy_limits[1]):
            errors.append(
                f"{pfx}: incident energy {el.incident_energy_eV} eV "
                f"outside range [{energy_limits[0]}, {energy_limits[1]}]"
            )

        if el.emission_energy_eV >= el.incident_energy_eV:
            errors.append(f"{pfx}: emission energy must be less than incident energy")

        if not (emiss_limits[0] <= el.emission_energy_eV <= emiss_limits[1]):
            errors.append(
                f"{pfx}: emission energy {el.emission_energy_eV} eV "
                f"outside range [{emiss_limits[0]}, {emiss_limits[1]}]"
            )

        if not re.match(r'^\d+\s+\d+\s+\d+$', el.crystal_hkl.strip()):
            errors.append(f"{pfx}: crystal hkl must be 3 integers (e.g. '6 4 2')")

        if el.n_crystals < 1 or el.n_crystals > 7:
            errors.append(f"{pfx}: number of crystals must be 1-7")

        if el.vortex_channel not in (1, 3):
            errors.append(f"{pfx}: vortex channel must be 1 or 3")

    return errors


def validate_experiment_data(data: dict) -> list[str]:
    """Validate experiment + elements submission data.
    Returns list of error strings (empty = valid).
    """
    errors = []
    defaults = _load_defaults()
    limits = defaults.get("motor_limits", {})

    # Experiment-level
    name = (data.get("experiment_name") or "").strip()
    if not name:
        errors.append("Experiment name is required")
    elif not re.match(r'^[a-zA-Z0-9_\-. ]+$', name):
        errors.append("Experiment name contains invalid characters (use letters, numbers, _ - .)")

    if not (data.get("experimenter") or "").strip():
        errors.append("Experimenter name is required")

    if data.get("mono_crystal") not in ("A", "B"):
        errors.append("Mono crystal must be A (Si111) or B (Si311)")

    if data.get("beam_size_h") not in ("big", "focused"):
        errors.append("Horizontal beam size must be big or focused")

    if data.get("beam_size_v") not in ("big", "focused"):
        errors.append("Vertical beam size must be big or focused")

    # mirrors_out is a boolean (or truthy string from form)
    mirrors_out = data.get("mirrors_out", False)
    if mirrors_out not in (True, False, 0, 1, "true", "false", "on", "off", ""):
        errors.append("mirrors_out must be a boolean")

    # Elements
    elements = data.get("elements", [])
    if not elements:
        errors.append("At least one element must be configured")

    energy_limits = limits.get("energy", [4950, 25000])
    emiss_limits = limits.get("emiss", [2000, 20000])
    seen_elements = set()

    for i, el in enumerate(elements, 1):
        pfx = f"Element {i}"
        sym = (el.get("symbol") or "").strip()
        if not sym:
            errors.append(f"{pfx}: element symbol is required")
        else:
            pfx = f"Element {i} ({sym})"
            if sym in seen_elements:
                errors.append(f"{pfx}: duplicate element")
            seen_elements.add(sym)

        try:
            inc = float(el.get("incident_energy", 0))
            if not (energy_limits[0] <= inc <= energy_limits[1]):
                errors.append(f"{pfx}: incident energy {inc} outside range {energy_limits}")
        except (ValueError, TypeError):
            errors.append(f"{pfx}: incident energy must be a number")

        try:
            emis = float(el.get("emission_energy", 0))
            if emis >= inc:
                errors.append(f"{pfx}: emission energy must be less than incident energy")
            if not (emiss_limits[0] <= emis <= emiss_limits[1]):
                errors.append(f"{pfx}: emission energy {emis} outside range {emiss_limits}")
        except (ValueError, TypeError):
            errors.append(f"{pfx}: emission energy must be a number")

        hkl = (el.get("crystal_hkl") or "").strip()
        if not re.match(r'^\d+\s+\d+\s+\d+$', hkl):
            errors.append(f"{pfx}: crystal hkl must be 3 integers (e.g. '6 4 2')")

        try:
            nc = int(el.get("n_crystals", 0))
            if nc < 1 or nc > 7:
                errors.append(f"{pfx}: number of crystals must be 1-7")
        except (ValueError, TypeError):
            errors.append(f"{pfx}: number of crystals must be an integer")

    return errors


def validate_sample_holder_data(data: dict, element_names: set[str] | None = None) -> list[str]:
    """Validate sample holder + samples submission data.
    element_names: set of valid element symbols from the experiment.
    Returns list of error strings (empty = valid).
    """
    errors = []
    defaults = _load_defaults()
    limits = defaults.get("motor_limits", {})

    if not (data.get("sample_holder_name") or "").strip():
        errors.append("Sample holder name is required")

    samples = data.get("samples", [])
    if not samples:
        errors.append("At least one sample is required")

    sample_names = set()
    any_enabled = False
    sx_limits = limits.get("Sx", [-10, 50])
    sy_limits = limits.get("Sy", [-10, 50])
    sz_limits = limits.get("Sz", [0, 50])

    for i, s in enumerate(samples, 1):
        pfx = f"Sample {i}"
        sname = (s.get("name") or "").strip()
        if not sname:
            errors.append(f"{pfx}: name is required")
        else:
            pfx = f"Sample {i} ({sname})"
            if sname in sample_names:
                errors.append(f"{pfx}: duplicate sample name")
            sample_names.add(sname)

        sel = (s.get("element") or "").strip()
        if not sel:
            errors.append(f"{pfx}: element is required")
        elif element_names is not None and sel not in element_names:
            errors.append(f"{pfx}: element '{sel}' is not in the configured elements list")

        enabled = s.get("enabled", True)
        if enabled:
            any_enabled = True

        # Positions are optional (pre-alignment), but if provided, check limits
        for motor, lim in [("sx", sx_limits), ("sy", sy_limits), ("sz", sz_limits)]:
            val_str = s.get(motor)
            if val_str is not None and val_str != "":
                try:
                    val = float(val_str)
                    if not (lim[0] <= val <= lim[1]):
                        errors.append(f"{pfx}: {motor} = {val} outside limits {lim}")
                except (ValueError, TypeError):
                    errors.append(f"{pfx}: {motor} must be a number")

        # XAS validation
        do_xas = s.get("do_xas", True)
        if do_xas:
            try:
                reps = int(s.get("xas_reps", 0))
                if reps < 1:
                    errors.append(f"{pfx}: XAS repetitions must be > 0")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: XAS repetitions must be an integer")

            try:
                ct = float(s.get("xas_time", 0))
                if ct <= 0:
                    errors.append(f"{pfx}: XAS count time must be > 0")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: XAS count time must be a number")

            try:
                filt = int(s.get("xas_filter", 0))
                if filt < 0 or filt > 255:
                    errors.append(f"{pfx}: XAS filter must be 0-255")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: XAS filter must be an integer")

        # RIXS validation
        do_rixs = s.get("do_rixs", False)
        if do_rixs:
            try:
                rt = float(s.get("rixs_time", 0))
                if rt <= 0:
                    errors.append(f"{pfx}: RIXS time must be > 0")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: RIXS time must be a number")

            try:
                rs = float(s.get("rixs_start", 0))
                re_val = float(s.get("rixs_end", 0))
                if rs <= re_val:
                    errors.append(f"{pfx}: RIXS start must be greater than end (scanning downward)")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: RIXS start/end must be numbers")

            try:
                rstep = float(s.get("rixs_step", 0))
                if rstep >= 0:
                    errors.append(f"{pfx}: RIXS step must be negative (scanning downward)")
            except (ValueError, TypeError):
                errors.append(f"{pfx}: RIXS step must be a number")

    if not any_enabled and samples:
        errors.append("At least one sample must be enabled")

    return errors


def validate_form_data(data: dict) -> list[str]:
    """Validate combined form submission (backwards compatibility).
    Returns list of error strings (empty = valid).
    """
    errors = validate_experiment_data(data)
    element_names = {
        (el.get("symbol") or "").strip()
        for el in data.get("elements", [])
        if (el.get("symbol") or "").strip()
    }
    errors += validate_sample_holder_data(data, element_names)
    return errors


# ---------------------------------------------------------------------------
# .mac file generation
# ---------------------------------------------------------------------------

def _generate_mac_content(
    experiment: Experiment,
    elements: list[ExperimentElement],
    sample_holder: SampleHolder,
    samples: list[SamplePosition],
) -> str:
    """Build the .mac file content string."""
    defaults = _load_defaults()
    gains = defaults.get("gains", {})
    crystal_key = "Si111" if experiment.mono_crystal == "A" else "Si311"
    crystal_gains = gains.get(crystal_key, {})

    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append(f"# AUTO-GENERATED by config_generator.py on {now} -- do not edit")
    lines.append(f"# Experiment: {sanitize_spec_string(experiment.name)}")
    lines.append(f"# Sample holder: {sanitize_spec_string(sample_holder.name)}")
    lines.append("")

    # --- Experiment-level globals ---
    lines.append("global EXPERIMENT_ID EXPERIMENT_NAME SAMPLE_HOLDER_NAME")
    lines.append("global MONO_CRYSTAL CRYSTAL_SET BEAM_SIZE_H BEAM_SIZE_V MIRRORS_OUT OPTIMIZED_ENERGY")
    lines.append("global N_ELEMENTS N_SAMPLES HOOKS_ENABLED HOOK_URL USER_DIR")
    lines.append("global I0_GAIN I0_OFFSET I1_GAIN")
    lines.append("global LLM_ENABLED LLM_DECIDE_ENABLED")
    lines.append("")

    lines.append(f'EXPERIMENT_ID = "{sanitize_spec_string(experiment.id)}"')
    lines.append(f'EXPERIMENT_NAME = "{sanitize_spec_string(experiment.name)}"')
    lines.append(f'SAMPLE_HOLDER_NAME = "{sanitize_spec_string(sample_holder.name)}"')
    lines.append(f'MONO_CRYSTAL = "{experiment.mono_crystal}"')
    lines.append(f'CRYSTAL_SET = "{experiment.mono_crystal}"')
    lines.append(f'BEAM_SIZE_H = "{experiment.beam_size_h}"')
    lines.append(f'BEAM_SIZE_V = "{experiment.beam_size_v}"')
    lines.append(f'MIRRORS_OUT = {1 if experiment.mirrors_out else 0}')
    lines.append('global beamsize_mode')
    lines.append(f'beamsize_mode["x"] = "{experiment.beam_size_h}"')
    lines.append(f'beamsize_mode["z"] = "{experiment.beam_size_v}"')

    # The optimized energy is the first element's incident energy
    opt_energy = elements[0].incident_energy_eV if elements else 0
    lines.append(f"OPTIMIZED_ENERGY = {opt_energy}")

    lines.append(f"N_ELEMENTS = {len(elements)}")
    lines.append(f"N_SAMPLES = {len(samples)}")

    # Data directory
    data_path = experiment.data_path or f"/data/fifteen/{_safe_filename(experiment.name)}"
    lines.append(f'USER_DIR = "{sanitize_spec_string(data_path)}"')

    # Hooks default on
    lines.append("HOOKS_ENABLED = 1")
    lines.append('HOOK_URL = "http://localhost:8005"')

    # LLM toggles
    lines.append("LLM_ENABLED = 1")
    lines.append("LLM_DECIDE_ENABLED = 1")

    # Gains
    i0_gain = crystal_gains.get("default_i0_gain", "100 nA/V")
    i1_gain = crystal_gains.get("default_i1_gain", "1 mA/V")
    i0_offset = crystal_gains.get("default_i0_offset", "10 pA")
    lines.append(f'I0_GAIN = "{i0_gain}"')
    lines.append(f'I0_OFFSET = "{i0_offset}"')
    lines.append(f'I1_GAIN = "{i1_gain}"')
    lines.append("")

    # --- Elements ---
    for i, el in enumerate(elements, 1):
        lines.append(f"# Element {i}: {el.element_symbol} {el.edge}")
        lines.append(
            f"global ELEMENT_{i}_NAME ELEMENT_{i}_EDGE "
            f"ELEMENT_{i}_INCIDENT ELEMENT_{i}_EMISSION"
        )
        lines.append(
            f"global ELEMENT_{i}_XES_SETUP ELEMENT_{i}_VORTEX_CH "
            f"ELEMENT_{i}_PLOTSELECT"
        )
        lines.append(
            f"global ELEMENT_{i}_CRYSTAL_TYPE ELEMENT_{i}_N_CRYSTALS "
            f"ELEMENT_{i}_ROW_RADIUS"
        )
        lines.append("")

        lines.append(f'ELEMENT_{i}_NAME = "{sanitize_spec_string(el.element_symbol)}"')
        lines.append(f'ELEMENT_{i}_EDGE = "{sanitize_spec_string(el.edge)}"')
        lines.append(f"ELEMENT_{i}_INCIDENT = {el.incident_energy_eV}")
        lines.append(f"ELEMENT_{i}_EMISSION = {el.emission_energy_eV}")

        # XES setup string: crystal_type h k l row_radius
        xes_setup = f"{el.crystal_type} {el.crystal_hkl} {el.row_radius}"
        lines.append(f'ELEMENT_{i}_XES_SETUP = "{xes_setup}"')

        lines.append(f"ELEMENT_{i}_VORTEX_CH = {el.vortex_channel}")
        plotselect = "vortDT2" if el.vortex_channel == 3 else "vortDT"
        lines.append(f'ELEMENT_{i}_PLOTSELECT = "{plotselect}"')
        lines.append(f"ELEMENT_{i}_CRYSTAL_TYPE = {el.crystal_type}")
        lines.append(f"ELEMENT_{i}_N_CRYSTALS = {el.n_crystals}")
        lines.append(f"ELEMENT_{i}_ROW_RADIUS = {el.row_radius}")
        lines.append("")

    # --- Samples ---
    for i, s in enumerate(samples, 1):
        lines.append(f"# Sample {i}: {s.sample_name}")
        lines.append(
            f"global SAMPLE_{i}_NAME SAMPLE_{i}_ELEMENT SAMPLE_{i}_ENABLED"
        )
        lines.append(
            f"global SAMPLE_{i}_SX SAMPLE_{i}_SY SAMPLE_{i}_SZ"
        )
        lines.append(
            f"global SAMPLE_{i}_DO_XAS SAMPLE_{i}_XAS_REPS "
            f"SAMPLE_{i}_XAS_TIME SAMPLE_{i}_XAS_FILTER SAMPLE_{i}_XAS_EMISS"
        )
        lines.append(
            f"global SAMPLE_{i}_DO_RIXS SAMPLE_{i}_RIXS_TIME "
            f"SAMPLE_{i}_RIXS_START SAMPLE_{i}_RIXS_END "
            f"SAMPLE_{i}_RIXS_STEP SAMPLE_{i}_RIXS_FILTER"
        )
        lines.append("")

        lines.append(f'SAMPLE_{i}_NAME = "{sanitize_spec_string(s.sample_name)}"')
        lines.append(f'SAMPLE_{i}_ELEMENT = "{sanitize_spec_string(s.element_symbol)}"')
        lines.append(f"SAMPLE_{i}_ENABLED = {1 if s.enabled else 0}")

        # Positions: use midpoint of lo/hi as the center position
        sx = (s.sx_lo + s.sx_hi) / 2 if (s.sx_lo != 0 or s.sx_hi != 0) else 0
        sy = (s.sy_lo + s.sy_hi) / 2 if (s.sy_lo != 0 or s.sy_hi != 0) else 0
        sz = (s.sz_lo + s.sz_hi) / 2 if (s.sz_lo != 0 or s.sz_hi != 0) else 0
        lines.append(f"SAMPLE_{i}_SX = {sx}")
        lines.append(f"SAMPLE_{i}_SY = {sy}")
        lines.append(f"SAMPLE_{i}_SZ = {sz}")

        # XAS
        lines.append(f"SAMPLE_{i}_DO_XAS = {1 if s.do_xas else 0}")
        lines.append(f"SAMPLE_{i}_XAS_REPS = {s.xas_reps}")
        lines.append(f"SAMPLE_{i}_XAS_TIME = {s.xas_time}")
        lines.append(f"SAMPLE_{i}_XAS_FILTER = {s.xas_filter}")

        # Emission energy: use override if set, otherwise look up from element
        xas_emiss = s.xas_emiss_override or s.emiss_energy_eV or 0
        lines.append(f"SAMPLE_{i}_XAS_EMISS = {xas_emiss}")

        # RIXS
        lines.append(f"SAMPLE_{i}_DO_RIXS = {1 if s.do_rixs else 0}")
        lines.append(f"SAMPLE_{i}_RIXS_TIME = {s.rixs_time}")
        lines.append(f"SAMPLE_{i}_RIXS_START = {s.rixs_start or 0}")
        lines.append(f"SAMPLE_{i}_RIXS_END = {s.rixs_end or 0}")
        lines.append(f"SAMPLE_{i}_RIXS_STEP = {s.rixs_step}")
        lines.append(f"SAMPLE_{i}_RIXS_FILTER = {s.rixs_filter}")

        # Sample boundary array for spot tracking
        lines.append(
            f"float array sample_{i}[1][10]"
        )
        lines.append(
            f"sample_{i} = {{"
            f"{s.sx_lo}, {s.sx_hi}, {s.sy_lo}, {s.sy_hi}, "
            f"{s.sz_lo}, {s.sz_hi}, {s.sx_del}, {s.sy_del}, "
            f"{s.sz_del}, {1 if s.enabled else 0}"
            f"}}"
        )
        lines.append("")

    lines.append(f'# End of config for {sanitize_spec_string(experiment.name)}')
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_config(experiment_id: str, output_path: str = None) -> str:
    """Read experiment from DB, generate config_generated.mac.

    Writes to output_path (default: macros/config_generated.mac).
    Also copies to /usr/local/lib/spec.d/config_generated.mac if writable.
    Uses atomic write (write to .tmp, then rename).

    Returns the generated .mac content as a string.
    """
    from db.client import get_session
    from sqlmodel import select

    exp = get_experiment(experiment_id)
    if exp is None:
        raise ValueError(f"Experiment {experiment_id} not found")

    elements = get_elements_for_experiment(experiment_id)
    if not elements:
        raise ValueError(f"No elements configured for experiment {experiment_id}")

    # Get the most recent sample holder
    with get_session() as session:
        stmt = (
            select(SampleHolder)
            .where(SampleHolder.experiment_id == experiment_id)
            .order_by(SampleHolder.created_at.desc())
        )
        holder = session.exec(stmt).first()

    if holder is None:
        raise ValueError(f"No sample holder found for experiment {experiment_id}")

    samples = get_samples_for_holder(holder.id)

    content = _generate_mac_content(exp, elements, holder, samples)

    # Write to local macros dir
    if output_path is None:
        output_path = str(_MACROS_DIR / "config_generated.mac")

    _atomic_write(output_path, content)

    # Try to copy to SPEC install location
    spec_path = _SPEC_INSTALL_DIR / "config_generated.mac"
    try:
        _atomic_write(str(spec_path), content)
    except (PermissionError, OSError):
        pass  # Not writable, that's fine — SPEC can load from macros/ too

    return content


def _atomic_write(path: str, content: str) -> None:
    """Write content to a file atomically (write .tmp then rename)."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate SPEC config from DB")
    parser.add_argument("--from-db", action="store_true", required=True)
    parser.add_argument("--experiment-id", type=str, default=None,
                        help="Experiment ID (default: active experiment)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path (default: macros/config_generated.mac)")
    args = parser.parse_args()

    if args.experiment_id:
        exp_id = args.experiment_id
    else:
        exp = get_active_experiment()
        if exp is None:
            print("No active experiment found. Create one via the web form.")
            raise SystemExit(1)
        exp_id = exp.id
        print(f"Using active experiment: {exp.name} ({exp_id})")

    # Validate first
    errors = validate_experiment(exp_id)
    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)

    content = generate_config(exp_id, args.output)
    output_path = args.output or str(_MACROS_DIR / "config_generated.mac")
    print(f"Config written to {output_path}")
    print(f"Generated {len(content)} bytes, {content.count(chr(10))} lines")


if __name__ == "__main__":
    main()
