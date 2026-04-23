"""Tool-layer test for every SPEC-bound entry in the /tools catalog.

One level *above* `scripts/unit_test_spec_cmd.py`: that test exercises
the CommandSpec dispatcher directly. This one invokes the actual tool
Python functions the LLM would call (the `t_*` wrappers in
`tools.autonomy_tools`, registered in `AUTONOMY_DISPATCH`) with
LLM-shaped `args` dicts, and checks that each one produces the expected
SPEC command on the wire.

Scope: only tools whose `TOOL_LINEAGE` entry has a non-None
`spec_command` — i.e., tools that actually send a SPEC command. Pure
orchestration tools (transition_phase, recent_actions, etc.) are
deliberately out of scope; the user asked us not to touch that layer.

For each tool we:

  1. Call the tool function with representative `args`.
  2. Assert the returned JSON has `ok: true` (or for special-cases like
     `abort_current_scan` and `get_i0_value`, the equivalent shape).
  3. Capture the SPEC command string(s) that actually hit the
     dispatcher (via a monkey-patched recorder on `_MockScreen.inject`),
     and compare to an expected value.

At the end, every unique macro token we dispatched is cross-checked
against a manually-curated list of what actually exists in
`/Users/kskoien/Documents/code/spec.d/`. Anything not found is flagged
as a candidate macro to write.

Runs in full SPEC_MOCK mode against a disposable SQLite DB — no real
SPEC, no orchestrator, no Slack.

    venv/bin/python scripts/unit_test_spec_tools.py

Exits 0 iff every check passed.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ---- Env + path setup ------------------------------------------------------
# Must happen before any server/* import so SPEC_MOCK + DB paths are honored.

os.environ.setdefault("SPEC_MOCK", "1")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_DB = ROOT / "data" / "spec_tools_units.db"
_DB.parent.mkdir(exist_ok=True)
if _DB.exists():
    _DB.unlink()
os.environ.setdefault("AUTONOMOUS_DB_PATH", str(_DB))
os.environ.setdefault("BEAMLINE_DB_PATH", str(_DB))

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "beamline_lib"))

from db import init_db as init_db_mod  # noqa: E402
from db.client import create_experiment  # noqa: E402
from spec import phase_allowlist, spec_cmd  # noqa: E402
from spec.screen_client import _MockScreen  # noqa: E402
from tools.autonomy_tools import AUTONOMY_DISPATCH  # noqa: E402
from tools.lineage import TOOL_LINEAGE  # noqa: E402


# ---- Dispatch recorder -----------------------------------------------------
# Every SPEC string we send to the mock screen is appended here. Tools
# that fan out to multiple SPEC calls (e.g. get_i0_value → ct + p S[I0])
# will accumulate multiple entries per tool invocation.

_DISPATCHED: list[str] = []
_orig_inject = _MockScreen.inject.__func__  # classmethod underlying fn


def _recording_inject(cls, cmd: str) -> str:
    _DISPATCHED.append(cmd)
    return _orig_inject(cls, cmd)


_MockScreen.inject = classmethod(_recording_inject)


def _reset_recorder() -> None:
    _DISPATCHED.clear()


# ---- spec.d macro catalog (from subagent audit of /Users/kskoien/Documents/code/spec.d/) ---

# Every command token here was confirmed to have a definition in the
# spec.d tree on 2026-04-23. Regenerate by re-running the
# `../spec.d/` audit if macros are added/removed.
KNOWN_MACROS: dict[str, str] = {
    # core motor/scan (mostly in standard.mac)
    "wa": "standard.mac:3716",
    "pwd": "standard.mac:54",
    "umv": "standard.mac:3421",
    "umvr": "standard.mac:3424",
    "mv": "standard.mac:3420",
    "ascan": "standard.mac:1120",
    "dscan": "standard.mac:1125",
    "ct": "standard.mac:3233",
    "fon": "standard.mac:80",
    # shutter
    "fson": "uniblitz.mac:61",
    "fsoff": "uniblitz.mac:84",
    "fsopen": "uniblitz.mac:20",
    "fsclose": "uniblitz.mac:33",
    # energy / gap
    "tracking": "tracking.mac:139",
    "gaprequest": "gapmotorBL152.mac:55",
    # filters / gains / roi
    "safely_remove_filters": "filter.mac:79",
    "set_i0_gain": "srs_set.mac:14",
    "set_i1_gain": "srs_set.mac:26",
    "set_i2_gain": "srs_set.mac:38",
    "vortex_roi": "vortex_roi.mac:44",
    # alignment procedures
    "peak_mono_pitch": "peak_mono_pitch.mac:24",
    "calibrate_mono": "theta.mac:78",
    "align_the_beamline": "beamline_align.mac:77",
    "run_spec_align": "xes_align_wrapped.mac:16",
    "auto_sample_align": "auto_sample_align.mac:39",
    "select_element": "select_element.mac:21",
    "run_collection": "run_collection.mac:24",
    # alignment shortcuts
    "vvv": "beam_diagnostics.mac:43",
    "hhh": "beam_diagnostics.mac:44",
    "ggg": "beam_diagnostics.mac:45",
    # per-element xas (verified Fe only; other element files exist in xas_macs/)
    "Fe_xas": "xas_macs/Fe_xas.mac:37",
    # per-element emission (only some elements have _cee — see audit)
    "As_cee": "xas_macs/As_xas.mac:51",
    "Gd_cee": "xas_macs/Gd_xas.mac:91",
    "Pb_cee": "xas_macs/Pb_xas.mac:48",
    # beam status helpers
    "get_beam_status": "check_beam.mac:49",
    "beam_status": "check_beam.mac:70",
    # file ops
    "newfile": "builtin",
}

# Tokens that are SPEC built-ins, not macros. Treated as existing.
KNOWN_BUILTINS: set[str] = {"p", "cen", "peak"}

# Tokens that are not real SPEC commands but internal sentinels we send
# through the dispatcher for side effects (e.g. abort → Ctrl-C on screen,
# SV_ABORT on TCP).
INTERNAL_SENTINELS: set[str] = {"__ABORT__"}


def _audit_tokens(spec_string: str) -> list[str]:
    """Pull every identifier worth auditing out of a rendered SPEC command.

    For most commands we only care about the leading token. But `p foo()`
    lines are interesting twice over: the builtin `p` plus the function
    `foo` that gets evaluated on the SPEC side. That second token is
    where drift like `get_beam_status` → `beam_status` hides, so we
    surface it explicitly. We also pick up the function name in
    ``func(args)`` calls at the start of a line.
    """
    s = spec_string.lstrip()
    out: list[str] = []

    lead = re.match(r"[A-Za-z_][A-Za-z0-9_]*|__[A-Z_]+__", s)
    if lead:
        out.append(lead.group(0))

    # `p <funcname>(...)` — audit the evaluated function too.
    pcall = re.match(r"p\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", s)
    if pcall:
        out.append(pcall.group(1))

    return out


def _macro_status(token: str) -> tuple[str, str]:
    """Return (status, detail) tagging a macro token's origin."""
    if token in INTERNAL_SENTINELS:
        return "SENTINEL", "internal sentinel, no SPEC macro"
    if token in KNOWN_BUILTINS:
        return "BUILTIN", "SPEC built-in"
    if token in KNOWN_MACROS:
        return "EXISTS", KNOWN_MACROS[token]
    return "MISSING", "no definition found in spec.d"


# ---- Test case definition --------------------------------------------------

@dataclass
class Case:
    """One tool-level test.

    * tool           — name in AUTONOMY_DISPATCH (i.e., the LLM-visible tool).
    * args           — dict we'd build from tool_use input JSON.
    * expected_spec  — the SPEC strings we expect to see on the wire, in
                       order. One tool call can produce multiple SPEC
                       sends (e.g. get_i0_value).
    * phase          — phase to set first. None leaves it.
    * expect_ok      — if True, returned JSON must include ok:true.
                       Set False for tools whose JSON shape differs.
    * note           — short free-form label for output.
    """
    tool: str
    args: dict
    expected_spec: list[str]
    phase: str | None = None
    expect_ok: bool = True
    note: str = ""


# ---- Cases, grouped by phase ----------------------------------------------

CASES_BL_ALIGN: list[Case] = [
    # CAT-0 procedurals
    Case("align_beamline",
         {"energy": 0, "xtal_chg": 0, "fine_x": 0, "fine_z": 0, "justification": "test"},
         ["align_the_beamline(0, 0, 0, 0, 0)"],
         phase=phase_allowlist.PHASE_BL_ALIGN,
         note="full beamline alignment"),
    Case("peak_mono_pitch",
         {"justification": "test"}, ["peak_mono_pitch"],
         note="mono piezo peak"),
    Case("calibrate_mono_from_foil_scan",
         {"tabulated_edge_ev": 7112, "justification": "test"},
         ["calibrate_mono 7112"],
         note="mono calibration from foil scan"),

    # CAT-1 motor control
    Case("move_motor",
         {"motor": "m1vert", "position": 1.93, "justification": "test"},
         ["umv m1vert 1.93"],
         note="absolute move"),
    Case("move_motor_relative",
         {"motor": "m1vert", "delta": 0.0, "justification": "test"},
         ["umvr m1vert 0.0"],
         note="relative move"),
    Case("read_motor_position",
         {"motor": "m1vert"}, ["p A[m1vert]"],
         note="read one motor"),
    Case("read_all_positions", {}, ["wa"],
         note="wa"),

    # CAT-2 scans
    Case("run_motor_scan",
         {"motor": "m1vert", "start": 1.92, "end": 1.94,
          "npoints": 3, "count_time": 0.1, "justification": "test"},
         ["ascan m1vert 1.92 1.94 3 0.1"],
         note="absolute scan"),
    Case("run_motor_scan_relative",
         {"motor": "m1vert", "delta_start": -0.01, "delta_end": 0.01,
          "npoints": 3, "count_time": 0.1, "justification": "test"},
         ["dscan m1vert -0.01 0.01 3 0.1"],
         note="delta scan"),

    # CAT-3 configuration
    Case("mv_energy",
         {"energy_ev": 7300, "justification": "test"},
         ["umv energy 7300"],
         note="plain energy move (tracking not auto-enabled)"),
    Case("shutter", {"command": "fsopen", "justification": "test"},
         ["fsopen"], note="open shutter"),
    Case("shutter", {"command": "fsclose", "justification": "test"},
         ["fsclose"], note="close shutter"),
    Case("shutter", {"command": "fson", "justification": "test"},
         ["fson"], note="auto-shutter on"),
    Case("shutter", {"command": "fson", "delay_s": 1.5, "justification": "test"},
         ["fson 1.5"], note="auto-shutter on w/ hold"),
    Case("shutter", {"command": "fsoff", "justification": "test"},
         ["fsoff"], note="auto-shutter off"),
    Case("set_filter", {"bitmask": 0, "justification": "test"},
         ["mv filter 0"], note="set filter bitmask"),
    Case("safely_remove_filters", {"justification": "test"},
         ["safely_remove_filters"], note="XRS-safe filter retract"),
    Case("set_gain", {"which": "i0", "gain_setting": "50 nA/V", "justification": "test"},
         ['set_i0_gain("50 nA/V")'], note="I0 SRS gain"),
    Case("set_gain", {"which": "i1", "gain_setting": "50 nA/V", "justification": "test"},
         ['set_i1_gain("50 nA/V")'], note="I1 SRS gain"),
    Case("set_gain", {"which": "i2", "gain_setting": "50 nA/V", "justification": "test"},
         ['set_i2_gain("50 nA/V")'], note="I2 SRS gain"),
    Case("set_vortex_roi",
         {"mode": "auto", "channel": 3, "justification": "test"},
         ["vortex_roi auto 3"], note="vortex ROI auto"),
    Case("set_vortex_roi",
         {"mode": "explicit", "channel": 3, "lo_ev": 100, "hi_ev": 200, "justification": "test"},
         ["vortex_roi 3 100 200"], note="vortex ROI explicit"),

    # CAT-4 alignment fallbacks
    Case("run_align_shortcut", {"name": "vvv", "justification": "test"},
         ["vvv"], note="named diagnostic"),
    Case("post_scan_move", {"mode": "cen", "justification": "test"},
         ["cen"], note="move to center"),
    Case("post_scan_move", {"mode": "peak", "justification": "test"},
         ["peak"], note="move to peak"),

    # CAT-6 beam monitoring (read-only)
    Case("get_beam_status", {}, ["p beam_status()"],
         note="beam snapshot (custom spec.d function)"),
    Case("get_i0_value", {"count_time": 0.5}, ["ct 0.5", "p S[I0]"],
         note="I0 via ct+p"),
    Case("request_gap_ownership", {"justification": "test"},
         ["gaprequest"], note="SPEAR gap request"),

    # CAT-7 run state
    Case("get_scan_number", {}, ["p SCAN_N"], note="current scan number"),
    Case("get_current_datafile", {}, ["fon"], note="active datafile"),
    Case("abort_current_scan", {"justification": "test"}, ["__ABORT__"],
         note="Ctrl-C"),
]

CASES_XES_ALIGN: list[Case] = [
    Case("align_xes_spectrometer",
         {"crystals": "1234567", "en_xes": 0, "en_mono": 0, "justification": "test"},
         ['run_spec_align("1234567", 0, 0)'],
         phase=phase_allowlist.PHASE_XES_ALIGN,
         note="7-crystal XES alignment"),
]

CASES_SAMPLE_ALIGN: list[Case] = [
    Case("run_sample_alignment", {"justification": "test"},
         ["auto_sample_align"],
         phase=phase_allowlist.PHASE_SAMPLE_ALIGN,
         note="per-sample centering"),
]

CASES_COLLECTION: list[Case] = [
    Case("select_element", {"element": "Fe", "justification": "test"},
         ['select_element("Fe")'],
         phase=phase_allowlist.PHASE_COLLECTION,
         note="switch to Fe geometry"),
    Case("open_data_file", {"filename": "smoke_test", "justification": "test"},
         ["newfile smoke_test"], note="start new SPEC file"),
    Case("run_xas",
         {"element": "Fe", "count_time": 0.1, "n_reps": 1, "justification": "test"},
         ["Fe_xas 0.1 1"], note="XAS — Fe, 2-arg form"),
    Case("run_xas",
         {"element": "Fe", "count_time": 0.1, "n_reps": 1,
          "emission_ev": 6400, "justification": "test"},
         ["Fe_xas 0.1 1 6400"], note="XAS — Fe, 3-arg form"),
    # Fe_cee is expected to be MISSING in spec.d — test anyway to surface it.
    Case("run_emiss_scan",
         {"element": "Fe", "count_time": 0.1, "n_reps": 1,
          "emission_ev": 6400, "filter": 0, "justification": "test"},
         ["Fe_cee 0.1 1 6400 0"], note="Fe emission scan (Fe_cee)"),
    # As_cee / Gd_cee / Pb_cee do exist — smoke-test one of them.
    Case("run_emiss_scan",
         {"element": "As", "count_time": 0.1, "n_reps": 1,
          "emission_ev": 11720, "filter": 0, "justification": "test"},
         ["As_cee 0.1 1 11720 0"], note="As emission scan (As_cee)"),
    Case("run_collection", {"justification": "test"},
         ["run_collection"], note="multi-sample loop"),
]

ALL_CASES: list[tuple[str, list[Case]]] = [
    ("BL_ALIGN tools", CASES_BL_ALIGN),
    ("XES_ALIGN tools", CASES_XES_ALIGN),
    ("SAMPLE_ALIGN tools", CASES_SAMPLE_ALIGN),
    ("COLLECTION tools", CASES_COLLECTION),
]


# ---- Runner ----------------------------------------------------------------

RESULTS: list[tuple[str, bool, str]] = []
DISPATCHED_TOKENS: set[str] = set()


def _record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"  {tag}  {name:<48}  {detail}")


def _check_ok_json(result_text: str) -> tuple[bool, Any]:
    try:
        obj = json.loads(result_text)
    except json.JSONDecodeError as e:
        return False, f"not JSON: {e}"
    return True, obj


def run_case(case: Case) -> None:
    fn: Callable[[dict], tuple[str, list[str]]] | None = AUTONOMY_DISPATCH.get(case.tool)
    label = f"{case.tool}[{case.note}]"
    if fn is None:
        _record(label, False, f"tool not in AUTONOMY_DISPATCH: {case.tool}")
        return

    if case.phase is not None:
        spec_cmd.set_phase(case.phase)

    _reset_recorder()
    try:
        text, _imgs = fn(dict(case.args))
    except Exception as e:
        _record(label, False, f"tool raised: {e!r}")
        return

    parsed_ok, parsed = _check_ok_json(text)
    if not parsed_ok:
        _record(label, False, str(parsed))
        return

    # get_i0_value returns {"ct": ..., "i0": ...} — not a single ok:true.
    # Treat "both sub-results dicts" as a success shape.
    if case.tool == "get_i0_value":
        sub_ok = (
            isinstance(parsed, dict)
            and isinstance(parsed.get("ct"), dict)
            and isinstance(parsed.get("i0"), dict)
            and parsed["ct"].get("ok") is True
            and parsed["i0"].get("ok") is True
        )
        if not sub_ok:
            _record(label, False, f"sub-results not both ok: {parsed}")
            return
    elif case.expect_ok:
        if parsed.get("ok") is not True:
            _record(label, False, f"ok!=true: {parsed}")
            return

    # Record every dispatched token for the end-of-run audit.
    for s in _DISPATCHED:
        for tok in _audit_tokens(s):
            DISPATCHED_TOKENS.add(tok)

    # Exact match on the dispatched SPEC strings. abort_current_scan is a
    # special case: spec_cmd.call("abort", ...) does NOT route through
    # the dispatcher — it calls screen_client.abort_current() directly.
    # So no recorder entry is expected; we just verify the CommandSpec
    # renderer would produce __ABORT__ as documented.
    if case.tool == "abort_current_scan":
        rendered = spec_cmd._ACTION["abort"].to_spec([])
        if rendered != "__ABORT__":
            _record(label, False,
                    f"abort renderer mismatch: got {rendered!r}")
            return
        DISPATCHED_TOKENS.add("__ABORT__")
        _record(label, True, "abort renders __ABORT__; dispatcher skipped (expected)")
        return

    if _DISPATCHED != case.expected_spec:
        _record(label, False,
                f"dispatch mismatch: expected {case.expected_spec}, "
                f"got {_DISPATCHED}")
        return

    _record(label, True, f"dispatched {case.expected_spec}")


# ---- Lineage coverage ------------------------------------------------------

def check_lineage_coverage() -> None:
    """Every tool whose TOOL_LINEAGE entry declares spec_command should
    be exercised at least once here. Fail if any SPEC-bound tool is
    missing a test case."""
    print("\n===== Lineage coverage =====")
    spec_bound = {
        name for name, meta in TOOL_LINEAGE.items()
        if meta.get("spec_command") is not None
    }
    # spec_command is the legacy BeamtimeHero umbrella tool with no
    # t_* wrapper — it isn't in AUTONOMY_DISPATCH. Skip here; if you
    # want coverage for the legacy dispatcher, test it separately.
    spec_bound.discard("spec_command")
    tested = {c.tool for _, cases in ALL_CASES for c in cases}
    missing = spec_bound - tested
    extra = tested - spec_bound
    ok = not missing and not extra
    _record(
        "every_spec_bound_tool_tested", ok,
        f"spec_bound={len(spec_bound)}, tested={len(tested)}, "
        f"missing={sorted(missing)}, extra={sorted(extra)}",
    )


# ---- Macro existence audit ------------------------------------------------

def audit_macros() -> int:
    """Classify every token we dispatched. Return count of MISSING macros."""
    print("\n===== spec.d macro existence audit =====")
    missing = 0
    for tok in sorted(DISPATCHED_TOKENS):
        status, detail = _macro_status(tok)
        if status == "EXISTS":
            print(f"  ✅  {tok:<26}  {detail}")
        elif status == "BUILTIN":
            print(f"  🧩  {tok:<26}  {detail}")
        elif status == "SENTINEL":
            print(f"  ⚙️   {tok:<26}  {detail}")
        else:
            print(f"  ❌  {tok:<26}  {detail}  ← write this")
            missing += 1
    return missing


# ---- Main ------------------------------------------------------------------

def main() -> int:
    init_db_mod.init_db()
    exp = create_experiment(
        name="spec-tool-units", experimenter="unittest",
        mono_crystal="A", beam_size_h="focused", beam_size_v="focused",
        sample_env="ambient",
    )
    spec_cmd.set_phase(phase_allowlist.PHASE_BL_ALIGN, experiment_id=exp.id)

    print(f"DB       : {os.environ['AUTONOMOUS_DB_PATH']}")
    print(f"SPEC_MOCK: {os.environ.get('SPEC_MOCK')}")
    print(f"EXP_ID   : {exp.id}")
    print(f"Tools    : {len(AUTONOMY_DISPATCH)} registered in AUTONOMY_DISPATCH")

    for group_name, cases in ALL_CASES:
        print(f"\n===== {group_name} =====")
        for case in cases:
            run_case(case)

    check_lineage_coverage()
    missing_macros = audit_macros()

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [(n, d) for n, ok, d in RESULTS if not ok]

    print()
    print("=" * 72)
    print(f"Total checks: {passed}/{total} passed")
    print(f"Missing macros (need to write): {missing_macros}")
    if failed:
        print("\nFailures:")
        for name, detail in failed:
            print(f"  {name}: {detail}")
    # Missing macros are a warning, not a test failure — they're the
    # whole point of the audit. Exit non-zero only on assertion failures.
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
