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
