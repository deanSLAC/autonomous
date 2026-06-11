"""Request-model validation for the config form (ui/server/schemas.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.server.schemas import (  # noqa: E402
    ExperimentIn,
    SampleHolderIn,
    validation_error_strings,
)


def _element(**over):
    base = {
        "symbol": "Fe", "edge": "K", "incident_energy": 7312,
        "emission_energy": 6404, "crystal_hkl": "4 4 0",
    }
    base.update(over)
    return base


def _experiment(**over):
    base = {
        "experiment_name": "2026-06_test",
        "mono_crystal": "A",
        "elements": [_element()],
    }
    base.update(over)
    return base


def test_valid_experiment_parses():
    req = ExperimentIn.model_validate(_experiment())
    assert req.elements[0].symbol == "Fe"
    assert req.beam_size_h == "big"
    assert req.calibration_foil_detector == "I2"


def test_form_strings_are_coerced():
    req = ExperimentIn.model_validate(_experiment(
        mirrors_out="true",
        elements=[_element(incident_energy="7312.0", n_crystals="5")],
    ))
    assert req.mirrors_out is True
    assert req.elements[0].incident_energy == 7312.0
    assert req.elements[0].n_crystals == 5


def test_missing_field_names_the_field():
    with pytest.raises(ValidationError) as exc:
        ExperimentIn.model_validate(_experiment(elements=[_element(symbol="")]))
    errors = validation_error_strings(exc.value)
    assert any("symbol" in e for e in errors)


def test_incident_energy_outside_beamline_range():
    with pytest.raises(ValidationError) as exc:
        ExperimentIn.model_validate(_experiment(
            elements=[_element(incident_energy=100000)],
        ))
    assert any("incident energy" in e for e in validation_error_strings(exc.value))


def test_emission_must_be_below_incident_for_xes():
    with pytest.raises(ValidationError):
        ExperimentIn.model_validate(_experiment(
            elements=[_element(emission_energy=9999999)],
        ))


def test_tfy_skips_xes_checks():
    req = ExperimentIn.model_validate(_experiment(
        elements=[_element(measurement_mode="tfy", emission_energy=0,
                           crystal_hkl="")],
    ))
    assert req.elements[0].measurement_mode == "TFY"


def test_duplicate_elements_rejected():
    with pytest.raises(ValidationError) as exc:
        ExperimentIn.model_validate(_experiment(
            elements=[_element(), _element()],
        ))
    assert any("duplicate element" in e for e in validation_error_strings(exc.value))


def test_bad_end_time_is_field_error_not_500():
    with pytest.raises(ValidationError) as exc:
        ExperimentIn.model_validate(_experiment(end_time="next tuesday"))
    assert any("end_time" in e for e in validation_error_strings(exc.value))


def test_blank_end_time_is_none():
    req = ExperimentIn.model_validate(_experiment(end_time=""))
    assert req.end_time is None


def test_foil_element_symbol_validated():
    with pytest.raises(ValidationError):
        ExperimentIn.model_validate(_experiment(calibration_foil_element="gold"))


# -- sample holder -----------------------------------------------------------

def _sample(**over):
    base = {"name": "FeO ref", "element": "Fe"}
    base.update(over)
    return base


def _holder(**over):
    base = {
        "experiment_id": "exp-1",
        "sample_holder_name": "rod A",
        "samples": [_sample()],
    }
    base.update(over)
    return base


def test_valid_holder_parses_with_defaults():
    req = SampleHolderIn.model_validate(_holder())
    s = req.samples[0]
    assert s.xas_time == 0.5 and s.do_xas is True and s.sx_lo == 0.0


def test_blank_position_strings_become_defaults():
    req = SampleHolderIn.model_validate(_holder(
        samples=[_sample(sx_lo="", sz_hi="12.5")],
    ))
    assert req.samples[0].sx_lo == 0.0
    assert req.samples[0].sz_hi == 12.5


def test_position_outside_motor_limits_rejected():
    with pytest.raises(ValidationError) as exc:
        SampleHolderIn.model_validate(_holder(samples=[_sample(sz_lo=999)]))
    assert any("Sz" in e for e in validation_error_strings(exc.value))


def test_duplicate_sample_names_rejected():
    with pytest.raises(ValidationError):
        SampleHolderIn.model_validate(_holder(
            samples=[_sample(), _sample()],
        ))


def test_rixs_direction_checks():
    with pytest.raises(ValidationError) as exc:
        SampleHolderIn.model_validate(_holder(samples=[_sample(
            do_rixs=True, rixs_start=7000, rixs_end=7100, rixs_step=0.2,
        )]))
    msgs = " ".join(validation_error_strings(exc.value))
    assert "start must be greater than end" in msgs or "step must be negative" in msgs


def test_all_samples_disabled_rejected():
    with pytest.raises(ValidationError):
        SampleHolderIn.model_validate(_holder(samples=[_sample(enabled=False)]))
