"""Request models for the UI HTTP boundary.

Validation strategy: validate at the edges, plain types inside. These
models replace the hand-rolled ``data.get(...)`` + ``float(...)``
coercion in the routers — a misspelled key or a list where a float was
expected used to become a KeyError/TypeError swallowed by a blanket
``except Exception`` → 500; now it's a field-named error string.

The config form's error contract is ``{"success": False, "errors":
[str, ...]}`` with HTTP 400 — `validation_error_strings` converts a
pydantic ValidationError into that shape so the frontend is untouched.

Beamline limits (motor ranges, energy ranges) come from
``config/defaults.yaml`` at validation time, same as the old
``config_generator.validate_*`` helpers.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ui.config import CONFIG_DIR

_DEFAULTS_PATH = CONFIG_DIR / "defaults.yaml"


def _motor_limits() -> dict:
    try:
        with open(_DEFAULTS_PATH) as f:
            return (yaml.safe_load(f) or {}).get("motor_limits", {})
    except OSError:
        return {}


def validation_error_strings(exc: ValidationError) -> list[str]:
    """Render a ValidationError as the form's list-of-strings contract."""
    out = []
    for err in exc.errors():
        loc = []
        for part in err["loc"]:
            if isinstance(part, int):
                loc[-1:] = [f"{loc[-1]}[{part + 1}]"] if loc else [f"[{part + 1}]"]
            else:
                loc.append(str(part))
        out.append(f"{'.'.join(loc) or 'request'}: {err['msg']}")
    return out


def _blank_to_none(v: Any) -> Any:
    if isinstance(v, str) and not v.strip():
        return None
    return v


# ---------------------------------------------------------------------------
# Experiment submission
# ---------------------------------------------------------------------------

class ElementIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(min_length=1)
    edge: str = Field(min_length=1)
    measurement_mode: Literal["XES", "TFY"] = "XES"
    emission_line: Optional[str] = None
    incident_energy: float
    emission_energy: float = 0
    crystal_type: int = 0
    crystal_hkl: str = "0 0 0"
    row_radius: int = 1000
    n_crystals: int = Field(default=3, ge=1, le=7)
    vortex_counter: str = "vortDT"

    @field_validator("symbol", "edge", "crystal_hkl", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("measurement_mode", mode="before")
    @classmethod
    def _upper_mode(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("emission_line", "emission_energy", "row_radius",
                     "n_crystals", "vortex_counter", "crystal_type", mode="before")
    @classmethod
    def _blank_optionalish(cls, v: Any, info) -> Any:
        v = _blank_to_none(v)
        if v is None:
            # fall back to the field default (mirrors `el.get(k) or default`)
            return cls.model_fields[info.field_name].get_default()
        return v

    @model_validator(mode="after")
    def _beamline_limits(self) -> "ElementIn":
        limits = _motor_limits()
        e_lo, e_hi = limits.get("energy", [4950, 25000])
        if not (e_lo <= self.incident_energy <= e_hi):
            raise ValueError(
                f"incident energy {self.incident_energy} outside range [{e_lo}, {e_hi}]"
            )
        if self.measurement_mode == "XES":
            m_lo, m_hi = limits.get("emiss", [2000, 20000])
            if self.emission_energy >= self.incident_energy:
                raise ValueError("emission energy must be less than incident energy")
            if not (m_lo <= self.emission_energy <= m_hi):
                raise ValueError(
                    f"emission energy {self.emission_energy} outside range [{m_lo}, {m_hi}]"
                )
            if not re.match(r"^\d+\s+\d+\s+\d+$", self.crystal_hkl):
                raise ValueError("crystal hkl must be 3 integers (e.g. '6 4 2')")
        return self


class ExperimentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    experiment_id: Optional[str] = None
    experiment_name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_\-. ]+$")
    experimenter: str = ""
    mono_crystal: Literal["A", "B"]
    beam_size_h: Literal["big", "focused"] = "big"
    beam_size_v: Literal["big", "focused"] = "big"
    mirrors_out: bool = False
    sample_env: str = "ambient"
    data_directory: str = ""
    calibration_foil_element: Optional[str] = None
    calibration_foil_detector: Literal["I1", "I2"] = "I2"
    end_time: Optional[datetime] = None
    elements: list[ElementIn] = Field(min_length=1)

    @field_validator("experiment_name", "experimenter", "data_directory", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("end_time", "experiment_id", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return _blank_to_none(v)

    @field_validator("calibration_foil_element", mode="before")
    @classmethod
    def _foil_element(cls, v: Any) -> Any:
        v = _blank_to_none(v)
        if v is None:
            return None
        v = str(v).strip()
        if not re.match(r"^[A-Z][a-z]?$", v):
            raise ValueError(
                "must be a chemical symbol (e.g. 'Au', 'Cu', 'Fe')"
            )
        return v

    @field_validator("calibration_foil_detector", mode="before")
    @classmethod
    def _foil_detector(cls, v: Any) -> Any:
        return "I2" if _blank_to_none(v) is None else v

    @model_validator(mode="after")
    def _no_duplicate_elements(self) -> "ExperimentIn":
        seen = set()
        for el in self.elements:
            if el.symbol in seen:
                raise ValueError(f"duplicate element {el.symbol}")
            seen.add(el.symbol)
        return self


# ---------------------------------------------------------------------------
# Small request bodies (chat, guidance, interventions, switches, misc)
# ---------------------------------------------------------------------------

class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    ui_session_id: Optional[str] = None
    author: str = "ui-user"

    @field_validator("message", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("author", "ui_session_id", mode="before")
    @classmethod
    def _blank(cls, v: Any, info) -> Any:
        v = _blank_to_none(v)
        if v is None and info.field_name == "author":
            return "ui-user"
        return v


class ChatClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_session_id: Optional[str] = None

    @field_validator("ui_session_id", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return _blank_to_none(v)


class GuidanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    author: str = "web-user"
    experiment_id: Optional[str] = None

    @field_validator("text", "author", mode="before")
    @classmethod
    def _strip(cls, v: Any, info) -> Any:
        v = _blank_to_none(v.strip() if isinstance(v, str) else v)
        if v is None and info.field_name == "author":
            return "web-user"
        return v


class ResolveInterventionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "denied"] = "resolved"
    resolver: str = "web-user"
    note: Optional[str] = None

    @field_validator("status", "resolver", mode="before")
    @classmethod
    def _blank(cls, v: Any, info) -> Any:
        v = _blank_to_none(v.strip() if isinstance(v, str) else v)
        if v is None:
            return cls.model_fields[info.field_name].get_default()
        return v


class SafetySwitchesIn(BaseModel):
    """Partial update — only the fields present in the request change."""

    model_config = ConfigDict(extra="forbid")

    spec_read_enabled: Optional[bool] = None
    spec_write_enabled: Optional[bool] = None


class HolderRefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holder_id: str = Field(min_length=1)


class HolderReorderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1)
    order: list[str] = Field(min_length=1)


class SpectrometerAlignedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: Optional[str] = None
    aligned: bool = True


class SlackStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    thread_ts: Optional[str] = None

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Sample holder submission (config form variant)
# ---------------------------------------------------------------------------

def _motor_range(name: str, fallback: list[float]) -> tuple[float, float]:
    lim = _motor_limits().get(name, fallback)
    return float(lim[0]), float(lim[1])


class HolderSampleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    element: str = Field(min_length=1)
    enabled: bool = True
    total_spots: int = 1
    sx_lo: float = 0.0
    sx_hi: float = 0.0
    sy_lo: float = 0.0
    sy_hi: float = 0.0
    sz_lo: float = 0.0
    sz_hi: float = 0.0
    sx_del: float = 0.0
    sy_del: float = 0.0
    sz_del: float = 0.0
    do_xas: bool = True
    xas_reps: int = 10
    xas_time: float = 0.5
    xas_filter: int = Field(default=0, ge=0, le=255)
    xas_emiss_override: Optional[float] = None
    do_rixs: bool = False
    rixs_time: float = 1.0
    rixs_start: Optional[float] = None
    rixs_end: Optional[float] = None
    rixs_step: float = -0.2
    rixs_filter: int = Field(default=0, ge=0, le=255)
    i0_gain: Optional[str] = None
    i0_offset: Optional[str] = None
    i1_gain: Optional[str] = None
    min_scans: Optional[int] = None

    @field_validator("name", "element", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator(
        "sx_lo", "sx_hi", "sy_lo", "sy_hi", "sz_lo", "sz_hi",
        "sx_del", "sy_del", "sz_del", "xas_reps", "xas_time", "xas_filter",
        "rixs_time", "rixs_step", "rixs_filter", "total_spots", mode="before",
    )
    @classmethod
    def _blank_to_default(cls, v: Any, info) -> Any:
        v = _blank_to_none(v)
        if v is None:
            return cls.model_fields[info.field_name].get_default()
        return v

    @field_validator("xas_emiss_override", "rixs_start", "rixs_end",
                     "min_scans", "i0_gain", "i0_offset", "i1_gain", mode="before")
    @classmethod
    def _blank_optional(cls, v: Any) -> Any:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _semantic_checks(self) -> "HolderSampleIn":
        for motor, attr_pairs, fallback in (
            ("Sx", (self.sx_lo, self.sx_hi), [-10, 50]),
            ("Sy", (self.sy_lo, self.sy_hi), [-10, 50]),
            ("Sz", (self.sz_lo, self.sz_hi), [0, 50]),
        ):
            lo, hi = _motor_range(motor, fallback)
            for val in attr_pairs:
                if val and not (lo <= val <= hi):
                    raise ValueError(
                        f"{motor} = {val} outside limits [{lo}, {hi}]"
                    )
        if self.do_xas and self.xas_time <= 0:
            raise ValueError("XAS count time must be > 0")
        if self.do_rixs:
            if self.rixs_time <= 0:
                raise ValueError("RIXS time must be > 0")
            if (self.rixs_start or 0) <= (self.rixs_end or 0):
                raise ValueError(
                    "RIXS start must be greater than end (scanning downward)"
                )
            if self.rixs_step >= 0:
                raise ValueError("RIXS step must be negative (scanning downward)")
        return self


# ---------------------------------------------------------------------------
# Plan-steering endpoints (plan_api)
# ---------------------------------------------------------------------------

class PlanEditIn(BaseModel):
    """Common fields on every plan-steering request."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: Optional[str] = None
    author: str = "web-user"
    reason: Optional[str] = None

    @field_validator("author", mode="before")
    @classmethod
    def _author_default(cls, v: Any) -> Any:
        v = _blank_to_none(v)
        return "web-user" if v is None else str(v).strip()


class AddSampleIn(PlanEditIn):
    sample_name: str = Field(min_length=1)
    element_symbol: str = Field(min_length=1)
    sample_id: Optional[str] = None
    holder_id: Optional[str] = None
    modes: Optional[list[dict]] = None
    position: Optional[int] = None

    @field_validator("sample_name", "element_symbol", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class SampleRefIn(PlanEditIn):
    sample_id: str = Field(min_length=1)
    note: Optional[str] = None


class ReorderIn(PlanEditIn):
    order: list[str] = Field(min_length=1)


class UpdateSampleIn(SampleRefIn):
    modes: Optional[list[dict]] = None
    status: Optional[str] = None
    snr_target: Optional[float] = None


class SetEndTimeIn(PlanEditIn):
    end_time: Optional[str] = None
    hours_from_now: Optional[float] = None

    @field_validator("end_time", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _exactly_one(self) -> "SetEndTimeIn":
        if (self.end_time is None) == (self.hours_from_now is None):
            raise ValueError("provide exactly one of end_time or hours_from_now")
        return self


class UpdateThresholdsIn(PlanEditIn):
    snr_target: Optional[float] = Field(default=None, gt=0)
    min_reps_per_sample: Optional[int] = Field(default=None, ge=0)
    max_drift_ev: Optional[float] = None


class SampleTimeBudgetIn(SampleRefIn):
    count_time_s: Optional[float] = Field(default=None, gt=0)
    reps: Optional[int] = Field(default=None, ge=0)
    mode: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "SampleTimeBudgetIn":
        if self.count_time_s is None and self.reps is None:
            raise ValueError("at least one of count_time_s or reps is required")
        return self


class HolderTimeBudgetIn(PlanEditIn):
    holder_id: Optional[str] = None
    count_time_s: Optional[float] = Field(default=None, gt=0)
    reps: Optional[int] = Field(default=None, ge=0)
    mode: Optional[str] = None
    apply_to_existing: bool = True

    @model_validator(mode="after")
    def _at_least_one(self) -> "HolderTimeBudgetIn":
        if self.count_time_s is None and self.reps is None:
            raise ValueError("at least one of count_time_s or reps is required")
        return self


class RegenerateIn(PlanEditIn):
    beamtime_hours: Optional[float] = Field(default=None, gt=0)


class SampleHolderIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    experiment_id: str = Field(min_length=1)
    sample_holder_name: str = Field(min_length=1)
    samples: list[HolderSampleIn] = Field(min_length=1)

    @field_validator("sample_holder_name", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _holder_checks(self) -> "SampleHolderIn":
        seen = set()
        for s in self.samples:
            if s.name in seen:
                raise ValueError(f"duplicate sample name {s.name!r}")
            seen.add(s.name)
        if not any(s.enabled for s in self.samples):
            raise ValueError("at least one sample must be enabled")
        return self
