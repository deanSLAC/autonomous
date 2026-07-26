"""Phase-report pipeline against real (simulated) SPEC files.

The historical failure mode was a report that rendered with every panel
blank — discovery silently matched nothing. These tests drive the real
pipeline end-to-end: simulation.engine writes genuine SPEC scan blocks
into a temp dir, the real scan cache parses them, and the real pickers
and matplotlib renderers run. Assertions check that discovery actually
matched scans (not just that a PNG file appeared).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamtimehero_cli import config as bl_config  # noqa: E402
from beamtimehero_cli.spec_data import local_data  # noqa: E402
from orchestration.agent import phase_reports  # noqa: E402
from simulation import engine  # noqa: E402


@dataclass
class _FakePhaseRun:
    experiment_id: str = "exp-1"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "running"


POSITIONS = [
    {
        "sample_number": 1, "sample_name": "FeO ref", "element_symbol": "Fe",
        "sx_lo": 1.0, "sx_hi": 2.0, "sy_lo": 1.0, "sy_hi": 2.0,
        "sz_lo": 9.0, "sz_hi": 11.0, "total_spots": 2,
        "emiss_energy_eV": 6404.0,
    },
    {
        "sample_number": 2, "sample_name": "Fe foil", "element_symbol": "Fe",
        "sx_lo": 1.0, "sx_hi": 2.0, "sy_lo": 1.0, "sy_hi": 2.0,
        "sz_lo": 19.0, "sz_hi": 21.0, "total_spots": 1,
        "emiss_energy_eV": 6404.0,
    },
]


@pytest.fixture
def spec_env(tmp_path, monkeypatch):
    """Real SPEC files under a temp BL_SCAN_DIR, parsed by the real cache."""
    scan_dir = tmp_path / "scans"
    engine.configure(scan_dir=scan_dir, default_file="test.01")

    # Beamline-alignment scans (motor names match the grid patterns).
    engine.append_ascan("monvtra", -1.0, 1.0, 21, 0.5)
    engine.append_ascan("m1vert", 1.7, 2.1, 41, 0.5)
    engine.append_ascan("m2horz", -0.2, 0.4, 31, 0.5)
    engine.append_ascan("pitcha", -0.05, 0.05, 21, 0.5)

    # Sample-alignment scans: wide Sz survey, then two per-sample blocks.
    survey = engine.append_ascan("Sz", 0.0, 45.0, 91, 0.2)   # survey (widest)
    s1 = [
        engine.append_ascan("Sz", 9.5, 10.5, 21, 0.2),       # sample 1 fine Sz
        engine.append_ascan("Sx", 0.5, 2.5, 21, 0.2),        # sample 1 Sx
        engine.append_ascan("Sy", 0.5, 2.5, 21, 0.2),        # sample 1 Sy
    ]
    s2 = [
        engine.append_ascan("Sz", 19.5, 20.5, 21, 0.2),      # sample 2 fine Sz
        engine.append_ascan("Sx", 0.5, 2.5, 21, 0.2),        # sample 2 Sx
    ]

    monkeypatch.setattr(bl_config, "BL_SCAN_DIR", scan_dir)
    local_data.clear_cache()
    monkeypatch.setattr(phase_reports, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(phase_reports, "_post_to_slack", lambda *a, **k: None)
    monkeypatch.setattr(phase_reports, "_alignment_metadata", lambda eid: {})
    monkeypatch.setattr(
        phase_reports, "_sample_positions_for_alignment", lambda eid: POSITIONS,
    )

    now = datetime.now()
    window = (now - timedelta(minutes=5), now + timedelta(minutes=5))
    yield {
        "scan_dir": scan_dir, "window": window, "now": now,
        "survey_scan": survey["scan_number"],
        "s1_scans": [r["scan_number"] for r in s1],
        "s2_scans": [r["scan_number"] for r in s2],
    }
    local_data.clear_cache()


def _stub_run(monkeypatch, window):
    run = _FakePhaseRun(started_at=window[0], completed_at=window[1])
    monkeypatch.setattr(phase_reports, "get_phase_run", lambda prid: run)
    return run


def test_window_matches_simulated_scans(spec_env):
    scans = phase_reports._scans_in_window(spec_env["window"])
    assert len(scans) == 10
    assert all(s.get("_dt") for s in scans)


def test_alignment_picker_fills_slots(spec_env):
    spec_datafile, scan_numbers = phase_reports._pick_alignment_scans(
        spec_env["window"],
    )
    assert spec_datafile and spec_datafile.endswith("test.01")
    matched = [n for n in scan_numbers if n is not None]
    # monvtra, m1vert, m2horz, pitch(a) slots must all have matched.
    assert len(matched) >= 4


def test_sample_alignment_picker_attributes_blocks(spec_env):
    spec_datafile, survey_scan, sample_scans, positions = (
        phase_reports._pick_sample_alignment_inputs("exp-1", spec_env["window"])
    )
    assert spec_datafile and spec_datafile.endswith("test.01")
    assert survey_scan == spec_env["survey_scan"]
    assert sample_scans == {
        1: spec_env["s1_scans"],
        2: spec_env["s2_scans"],
    }
    assert positions == POSITIONS


def test_generate_and_post_alignment_renders_png(spec_env, monkeypatch):
    _stub_run(monkeypatch, spec_env["window"])
    out = phase_reports.generate_and_post("beamline_alignment", "pr-1")
    assert out.error is None and out.path is not None
    png = Path(out.path)
    assert png.exists() and png.stat().st_size > 20_000
    assert "alignment_pr-1" in png.name


def test_generate_and_post_sample_alignment_renders_png(spec_env, monkeypatch):
    _stub_run(monkeypatch, spec_env["window"])
    out = phase_reports.generate_and_post("sample_alignment", "pr-2")
    assert out.error is None and out.path is not None
    png = Path(out.path)
    assert png.exists() and png.stat().st_size > 20_000
    assert "sample_alignment_pr-2" in png.name


def test_window_pad_absorbs_clock_skew(spec_env, monkeypatch):
    # PhaseRun clock runs a minute ahead of the SPEC host: an unpadded
    # window would miss every scan; the pad must keep them in.
    late = (spec_env["now"] + timedelta(seconds=60),
            spec_env["now"] + timedelta(minutes=5))
    _stub_run(monkeypatch, late)
    out = phase_reports.generate_and_post("beamline_alignment", "pr-3")
    assert out.path is not None, out.error


def test_unhandled_slug_is_not_applicable_not_a_failure(spec_env, monkeypatch):
    """A slug with no report must report neither a path nor an error — the UI
    shows nothing, which is correct here and only here."""
    _stub_run(monkeypatch, spec_env["window"])
    out = phase_reports.generate_and_post("collection", "pr-4")
    assert out.path is None and out.error is None
    assert out.failed is False


def test_empty_window_reports_why_instead_of_returning_none(spec_env, monkeypatch):
    """REGRESSION: every failure used to return a bare None, which the phase page
    rendered identically to "no report". A report that was attempted and failed
    must carry a reason; this is the case that hid four render bugs for a month."""
    far_future = (spec_env["now"] + timedelta(days=30),
                  spec_env["now"] + timedelta(days=30, minutes=5))
    _stub_run(monkeypatch, far_future)
    out = phase_reports.generate_and_post("beamline_alignment", "pr-5")
    assert out.path is None
    assert out.failed is True
    assert "no usable scans" in out.error
    assert "clock-skew pad" in out.error   # says what window was searched


def test_missing_phase_run_row_reports_why(spec_env, monkeypatch):
    monkeypatch.setattr(phase_reports, "get_phase_run", lambda _pid: None)
    out = phase_reports.generate_and_post("beamline_alignment", "pr-6")
    assert out.failed and "not found" in out.error


def test_renderer_exception_is_surfaced_with_its_type(spec_env, monkeypatch):
    _stub_run(monkeypatch, spec_env["window"])
    def boom(*_a, **_k):
        raise ValueError("matplotlib exploded")
    monkeypatch.setattr(phase_reports, "_render_alignment", boom)
    out = phase_reports.generate_and_post("beamline_alignment", "pr-7")
    assert out.failed
    assert "ValueError" in out.error and "matplotlib exploded" in out.error


def test_xes_alignment_is_routed(spec_env, monkeypatch):
    """spectrometer_report was complete, working code with zero callers; the
    xes_alignment slug now reaches it."""
    _stub_run(monkeypatch, spec_env["window"])
    seen = {}
    def fake(**kw):
        seen.update(kw)
        out = Path(kw["output_dir"]) / "spectrometer_pr-8.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x89PNG" + b"0" * 100)
        return str(out)
    from orchestration.agent import reports
    monkeypatch.setattr(reports, "spectrometer_report", fake)
    monkeypatch.setattr(phase_reports, "_pick_spectrometer_scans",
                        lambda _w: ("/data/fake/specdata01", [11, 12, 13]))
    monkeypatch.setattr(phase_reports, "_resolve_spec_datafile",
                        lambda n: "/data/fake/specdata01")
    out = phase_reports.generate_and_post("xes_alignment", "pr-8")
    assert out.error is None and out.path is not None
    assert seen["scan_numbers"] == [11, 12, 13]


def test_crystal_scan_regex_matches_axes_not_counters():
    m = phase_reports._CRYSTAL_SCAN_RE
    assert m.match("c1y") and m.match("c7p") and m.match("c58y")
    # analyser counters and the mono `crystal` motor must not match
    assert not m.match("c5") and not m.match("crystal") and not m.match("c1z")
