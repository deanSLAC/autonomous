"""Per-tool lineage metadata for the /tools catalog page.

Every LLM-callable tool in :mod:`tools.definitions` and
:mod:`tools.autonomy_definitions` has an entry here. The metadata is
used by the ``/api/tools`` endpoint to render the "what the agent can
do" page with expanded descriptions, input/output shape, data source,
and cross-tool dependencies.

Schema per entry:

    long_description : str
        A few sentences elaborating on the one-line schema description.
    python_func : str
        The concrete Python call chain the executor performs. Shown in
        the UI so operators can trace a tool call to its implementation.
    spec_command : str | None
        The literal SPEC macro/command string (or multi-call chain) sent
        to the running SPEC session. ``None`` for tools that don't touch
        SPEC. Tools with a non-None value appear in the "SPEC-bound"
        section of the page.
    output : str
        One-line description of what the tool returns.
    source : str
        Enum. Used to group tools visually and to colour the source
        badge. Values:
          * ``spec_datafile``  — reads a .dat SPEC file from BL_SCAN_DIR
          * ``spec_session``   — issues a command to the live SPEC session
          * ``spec_logfile``   — reads beamline control log files
          * ``spec_config``    — reads SPEC's config file
          * ``autonomy_db``    — reads/writes the autonomy SQLite DB
          * ``filesystem``     — non-SPEC files in the scan directory
          * ``tool_chain``     — consumes the output of another tool
          * ``slack``          — sends a message to staff Slack
    source_detail : str
        Human-readable specifics about where the data comes from.
    depends_on : list[str]
        Other tools typically called first to obtain required arguments
        (e.g. ``list_scans`` before ``read_scan``). Empty when the tool
        has no prerequisite in the tool chain.
"""

from __future__ import annotations


TOOL_LINEAGE: dict[str, dict] = {

    # ---------- BeamtimeHero read-only tools (server/tools/definitions.py) ---

    "get_latest_scan": {
        "long_description": (
            "Return the most recently modified SPEC scan on disk, along "
            "with its metadata (file, scan number, command, counters) and "
            "a small numeric preview of the scan's points."
        ),
        "python_func": "blmcp.tools.get_latest_scan()",
        "spec_command": None,
        "output": "JSON: {file_name, scan_number, command, counters, data_preview}",
        "source": "spec_datafile",
        "source_detail": (
            "Reads .dat files under BL_SCAN_DIR via silx.io.specfile; "
            "metadata pulled from the sidecar .scan_metadata_cache.json."
        ),
        "depends_on": [],
    },
    "list_scans": {
        "long_description": (
            "Enumerate recent SPEC scans with metadata so the agent can "
            "pick a file_name/scan_number pair for follow-up tools."
        ),
        "python_func": "blmcp.tools.list_scans(limit=20)",
        "spec_command": None,
        "output": "JSON array: [{file_name, scan_number, command, counters, npoints, timestamp}, ...]",
        "source": "spec_datafile",
        "source_detail": "SPEC file headers (#S, #D, #T, #L, #P) cached in .scan_metadata_cache.json.",
        "depends_on": [],
    },
    "read_scan": {
        "long_description": (
            "Return the full data array of a single scan, addressed by "
            "file_name + scan_number. Use list_scans first to discover the "
            "valid identifiers."
        ),
        "python_func": "blmcp.tools.read_scan(file_name, scan_number)",
        "spec_command": None,
        "output": "JSON: {metadata, counters, data: {col: [values]}}",
        "source": "spec_datafile",
        "source_detail": "Parses the #S block of the SPEC file via silx.io.specfile.",
        "depends_on": ["list_scans"],
    },
    "get_latest_log_entries": {
        "long_description": (
            "Return the tail of the beamline control log. The agent uses "
            "this to see what SPEC just printed — prompts, warnings, the "
            "text of recent commands."
        ),
        "python_func": "blmcp.tools.get_latest_log_entries(lines=100)",
        "spec_command": None,
        "output": "JSON: {log_file, lines: [str]}",
        "source": "spec_logfile",
        "source_detail": "Reads the newest file under BL_LOGS_DIR.",
        "depends_on": [],
    },
    "search_logs": {
        "long_description": (
            "Grep-like search across beamline control logs for a literal "
            "string (error message, motor name, macro name). Returns a "
            "bounded match list."
        ),
        "python_func": "blmcp.tools.search_logs(query, max_results=50)",
        "spec_command": None,
        "output": "JSON array: [{log_file, line_number, line}, ...]",
        "source": "spec_logfile",
        "source_detail": "Scans all files under BL_LOGS_DIR via bllogs_converter/log_parser.",
        "depends_on": [],
    },
    "list_logs": {
        "long_description": (
            "List the available log files in BL_LOGS_DIR with their sizes "
            "and modification times."
        ),
        "python_func": "blmcp.tools.list_logs(limit=20)",
        "spec_command": None,
        "output": "JSON array: [{name, size, mtime}, ...]",
        "source": "spec_logfile",
        "source_detail": "Directory listing of BL_LOGS_DIR.",
        "depends_on": [],
    },
    "get_active_counter": {
        "long_description": (
            "Pick the 'meaningful' counter for an energy scan. Heuristic: "
            "ppboff if it exists, else the vortDT/vortDT2/vortDT3/vortDT4 "
            "with the highest max count, else I1."
        ),
        "python_func": "blmcp.tools.get_active_counter(file_name, scan_number)",
        "spec_command": None,
        "output": "JSON: {counter: str, reason: str}",
        "source": "spec_datafile",
        "source_detail": "Reads per-point counter values from the SPEC scan.",
        "depends_on": ["list_scans"],
    },
    "get_scan_deadtime": {
        "long_description": (
            "Compute how much of a scan was acquisition vs overhead "
            "(motor moves, settling, comms). Useful when optimizing "
            "count time or diagnosing slow scans."
        ),
        "python_func": "blmcp.tools.get_scan_deadtime(file_name, scan_number)",
        "spec_command": None,
        "output": "JSON: {wall_s, acq_s, dead_s, dead_pct}",
        "source": "spec_datafile",
        "source_detail": "Uses per-point timestamps and #T header from the SPEC scan.",
        "depends_on": ["list_scans"],
    },
    "normalize_scan": {
        "long_description": (
            "Edge-step normalize an energy scan: divide the signal by I0 "
            "(or any chosen reference), then linearly rescale so the "
            "pre-edge reads 0 and the post-edge reads 1."
        ),
        "python_func": "blmcp.tools.edge_step_normalize_scan(file_name, scan_number, counter, normalize_by)",
        "spec_command": None,
        "output": "JSON: {x: [energy], y: [normalized], counter, normalize_by}",
        "source": "spec_datafile",
        "source_detail": "Reads counter + I0 arrays from the SPEC scan.",
        "depends_on": ["list_scans", "get_active_counter"],
    },
    "average_scans": {
        "long_description": (
            "Edge-step normalize every energy scan in a file, then average "
            "them. Returns the mean, the point-wise standard deviation, "
            "and the number of scans averaged."
        ),
        "python_func": "blmcp.tools.average_energy_scans(file_name)  |  average_latest_energy_scans()",
        "spec_command": None,
        "output": "JSON: {x, mean, std, n_scans, file_name}",
        "source": "spec_datafile",
        "source_detail": "Iterates every #S block in the SPEC file.",
        "depends_on": ["list_scans"],
    },
    "analyze_convergence": {
        "long_description": (
            "Answer 'do I have enough scans?' via cosine similarity of "
            "each scan to the running mean, plus cumulative convergence "
            "and standard error."
        ),
        "python_func": "blmcp.tools.analyze_scan_convergence(file_name)",
        "spec_command": None,
        "output": "JSON: {per_scan_similarity, cumulative, std_error, verdict}",
        "source": "spec_datafile",
        "source_detail": "Same scan set used by average_scans.",
        "depends_on": ["average_scans"],
    },
    "analyze_efficiency": {
        "long_description": (
            "Comprehensive scan-repetition efficiency report: "
            "convergence, coefficient of variation, comparison to the "
            "Poisson statistical limit, and a terminal verdict "
            "(needs_more / reasonable / marginal / wasteful)."
        ),
        "python_func": "blmcp.tools.analyze_scan_efficiency(file_name)",
        "spec_command": None,
        "output": "JSON: {convergence, cv, poisson_ratio, recommended_n, verdict}",
        "source": "spec_datafile",
        "source_detail": "Superset of analyze_convergence.",
        "depends_on": ["analyze_convergence"],
    },
    "plot_scan": {
        "long_description": (
            "Render one scan as a PNG and return it to the user. Auto-"
            "detects the active counter; accepts an optional "
            "normalize_by counter."
        ),
        "python_func": "blmcp.tools.plot_scan(file_name, scan_number, counter, normalize_by)",
        "spec_command": None,
        "output": "Base64 PNG + a one-line caption",
        "source": "spec_datafile",
        "source_detail": "Reads the scan via silx, renders with matplotlib.",
        "depends_on": ["list_scans", "get_active_counter"],
    },
    "plot_averaged_scans": {
        "long_description": (
            "Edge-step normalize every scan in each given SPEC file, "
            "average, and overlay all samples on one plot with std-dev "
            "shading. The go-to cross-sample comparison plot."
        ),
        "python_func": "blmcp.tools.plot_averaged_scans_overlay(file_names)",
        "spec_command": None,
        "output": "Base64 PNG + a short text summary",
        "source": "spec_datafile",
        "source_detail": "Multiple SPEC files under BL_SCAN_DIR.",
        "depends_on": ["list_scans", "average_scans"],
    },
    "plot_data": {
        "long_description": (
            "General-purpose line plotter. The agent passes raw arrays — "
            "typically grabbed from read_scan or normalize_scan — and "
            "gets back a rendered PNG. Supports up to four overlaid series."
        ),
        "python_func": "matplotlib.pyplot (in-process, via bldata_analysis.plotting)",
        "spec_command": None,
        "output": "Base64 PNG + a one-line caption",
        "source": "tool_chain",
        "source_detail": "Pure rendering — x/y arrays come from other tools or the conversation.",
        "depends_on": ["read_scan", "normalize_scan"],
    },
    "list_files": {
        "long_description": (
            "List non-SPEC files (macros, configs, notes) in the scan "
            "directory so the agent can decide what to read or edit."
        ),
        "python_func": "local_data.list_files(pattern)",
        "spec_command": None,
        "output": "JSON array: [{name, size, mtime}, ...]",
        "source": "filesystem",
        "source_detail": "Glob within BL_SCAN_DIR (excluding .dat SPEC files).",
        "depends_on": [],
    },
    "read_file": {
        "long_description": (
            "Read a text file from the scan directory — typically a .mac "
            "macro the agent wants to inspect or edit."
        ),
        "python_func": "local_data.read_file(path)",
        "spec_command": None,
        "output": "Raw text file contents",
        "source": "filesystem",
        "source_detail": "Arbitrary text file under BL_SCAN_DIR.",
        "depends_on": ["list_files"],
    },
    "write_summary": {
        "long_description": (
            "Persist a conversation summary into the scan directory as a "
            "timestamped .txt file. Used so operators can review agent "
            "reasoning offline."
        ),
        "python_func": "local_data.write_file(beamtimehero_conversation_summary_<ts>.txt, content)",
        "spec_command": None,
        "output": "Relative path of the written file",
        "source": "filesystem",
        "source_detail": "Writes into BL_SCAN_DIR.",
        "depends_on": [],
    },
    "write_macro": {
        "long_description": (
            "Save an edited SPEC macro under a new name with a "
            "_heroic_<date> suffix so the original macro is never "
            "overwritten."
        ),
        "python_func": "local_data.write_file(<original>_heroic_<date>.mac, content)",
        "spec_command": None,
        "output": "Relative path of the new .mac file",
        "source": "filesystem",
        "source_detail": "Writes into BL_SCAN_DIR alongside existing macros.",
        "depends_on": ["read_file"],
    },
    "get_motor_config": {
        "long_description": (
            "Return SPEC's motor table: per-motor controller, steps/unit, "
            "slew rate, flags, and mnemonic. The motor index (MOTnnn) "
            "maps directly to the A[] array in SPEC."
        ),
        "python_func": "spec_config.get_motor_config()",
        "spec_command": None,
        "output": "Plain-text table (one row per motor)",
        "source": "spec_config",
        "source_detail": "Parses the SPEC config file on disk.",
        "depends_on": [],
    },
    "get_counter_config": {
        "long_description": (
            "Return SPEC's counter table: per-counter controller, unit, "
            "channel, scale, flags, and mnemonic. The counter index "
            "(CNTnnn) maps to the S[] array."
        ),
        "python_func": "spec_config.get_counter_config()",
        "spec_command": None,
        "output": "Plain-text table (one row per counter)",
        "source": "spec_config",
        "source_detail": "Parses the SPEC config file on disk.",
        "depends_on": [],
    },
    "spec_command": {
        "long_description": (
            "Send one of a tiny allow-list of *read-only* SPEC commands "
            "(wa / pwd / fon / get_S) and return the log output. The "
            "hard allow-list makes this safe to expose to the LLM."
        ),
        "python_func": "spec_client.send_spec_command(command)",
        "spec_command": "wa | pwd | fon | get_S",
        "output": "Plain text from the SPEC log",
        "source": "spec_session",
        "source_detail": "Routes through the SPEC command channel; bypasses the action_log since it's read-only.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-0: procedures --------------------------

    "align_beamline": {
        "long_description": (
            "Run the full beamline alignment macro. Multi-minute: "
            "optimizes M1/M2, peaks mono pitch, aligns the mono slits, "
            "optimizes the B stage, zeros the pinhole, measures beam "
            "size. One-shot — refuses a re-run if the action_log shows "
            "it already succeeded this experiment."
        ),
        "python_func": "spec_cmd.call('align_beamline', [energy, xtal_chg, fine_x, fine_z], justification)",
        "spec_command": "align_the_beamline(<energy>, 0, <xtal_chg>, <fine_x>, <fine_z>)",
        "output": "JSON: {ok, action_id, spec_result}",
        "source": "spec_session",
        "source_detail": "Writes action_log row before SPEC dispatch; blocks until SPEC prompt returns.",
        "depends_on": ["transition_phase"],
    },
    "align_xes_spectrometer": {
        "long_description": (
            "Align the 7-crystal HERFD analyzer via run_spec_align. "
            "One-shot per experiment. Crystals arg selects a subset "
            "(e.g. '1234' aligns only crystals 1–4)."
        ),
        "python_func": "spec_cmd.call('align_xes', [crystals, en_xes, en_mono], justification)",
        "spec_command": 'run_spec_align("<crystals>", <en_xes>, <en_mono>)',
        "output": "JSON: {ok, action_id, per_crystal_pitch_roll, xes_en_offset}",
        "source": "spec_session",
        "source_detail": "Gated to phase xes_alignment by the phase allow-list.",
        "depends_on": ["align_beamline", "transition_phase"],
    },
    "run_sample_alignment": {
        "long_description": (
            "Run auto_sample_align: Sz survey plus per-sample centering. "
            "Populates each sample's Sx/Sy/Sz in the plan."
        ),
        "python_func": "spec_cmd.call('auto_sample_align', [], justification)",
        "spec_command": "auto_sample_align",
        "output": "JSON: {ok, action_id, samples: [{id, Sx, Sy, Sz}, ...]}",
        "source": "spec_session",
        "source_detail": "Gated to phase sample_alignment.",
        "depends_on": ["align_xes_spectrometer"],
    },
    "run_collection": {
        "long_description": (
            "Multi-sample data-collection loop. Cycles through every "
            "enabled sample, producing one SPEC file per sample."
        ),
        "python_func": "spec_cmd.call('run_collection', [], justification)",
        "spec_command": "run_collection",
        "output": "JSON: {ok, action_id, files_opened}",
        "source": "spec_session",
        "source_detail": "Gated to phase collection; emits SPEC data files into BL_SCAN_DIR.",
        "depends_on": ["run_sample_alignment"],
    },
    "select_element": {
        "long_description": (
            "Switch the beamline to the configured per-element geometry "
            "— sets energy, emission energy, Vortex ROI, and runs "
            "xes_setup."
        ),
        "python_func": "spec_cmd.call('select_element', [element], justification)",
        "spec_command": 'select_element("<element>")',
        "output": "JSON: {ok, action_id}",
        "source": "spec_session",
        "source_detail": "Pulls the target geometry from the experiment plan.",
        "depends_on": ["get_experiment_plan"],
    },
    "peak_mono_pitch": {
        "long_description": (
            "LVDT-driven piezo optimization of the 2nd mono crystal "
            "pitch. Used as a fallback or pre-scan tune-up."
        ),
        "python_func": "spec_cmd.call('peak_mono_pitch', [], justification)",
        "spec_command": "peak_mono_pitch",
        "output": "JSON: {ok, action_id, new_pitch}",
        "source": "spec_session",
        "source_detail": "Short macro; typically runs in seconds.",
        "depends_on": [],
    },
    "calibrate_mono_from_foil_scan": {
        "long_description": (
            "Standard mono calibration: dscan energy ±15 eV over a "
            "reference foil, find the inflection, then call "
            "calibrate_mono + reset_gap. The tabulated edge energy must "
            "be within 5 eV of the current energy."
        ),
        "python_func": "spec_cmd.call('calibrate_mono', [tabulated_edge_ev], justification)",
        "spec_command": "calibrate_mono <tabulated_edge_ev>",
        "output": "JSON: {ok, action_id, inflection_ev, offset_ev}",
        "source": "spec_session",
        "source_detail": "Chained under the hood: dscan → find inflection → calibrate_mono → reset_gap.",
        "depends_on": ["run_motor_scan_relative"],
    },

    # ---------- Autonomy tools — CAT-1: motor control -----------------------

    "move_motor": {
        "long_description": (
            "Absolute motor move (SPEC's umv). Motor must be on the "
            "current phase's allow-list — e.g. during sample_alignment "
            "only Sx/Sy/Sz are movable."
        ),
        "python_func": "spec_cmd.call('umv', [motor, position], justification)",
        "spec_command": "umv <motor> <position>",
        "output": "JSON: {ok, action_id, final_position}",
        "source": "spec_session",
        "source_detail": "Synchronous — blocks until the motor reports done.",
        "depends_on": [],
    },
    "move_motor_relative": {
        "long_description": (
            "Relative motor move (SPEC's umvr) — shift a motor by a "
            "delta from its current position. Same phase allow-list as "
            "move_motor."
        ),
        "python_func": "spec_cmd.call('umvr', [motor, delta], justification)",
        "spec_command": "umvr <motor> <delta>",
        "output": "JSON: {ok, action_id, final_position}",
        "source": "spec_session",
        "source_detail": "Synchronous motor move via the SPEC prompt.",
        "depends_on": ["read_motor_position"],
    },
    "read_motor_position": {
        "long_description": (
            "Read a single motor's position as a parsed float. Read-only "
            "— does not require a justification."
        ),
        "python_func": "spec_cmd.call('p_motor', [motor], justification='')",
        "spec_command": "p A[<motor>]",
        "output": "JSON: {motor, position}",
        "source": "spec_session",
        "source_detail": "Read-only query; logs to query_log, not action_log.",
        "depends_on": [],
    },
    "read_all_positions": {
        "long_description": (
            "Read every motor's current position. Wraps SPEC's wa and "
            "parses the output into a {name → value} map."
        ),
        "python_func": "spec_cmd.call('wa', [], justification='')",
        "spec_command": "wa",
        "output": "JSON: {motor_name: position, ...}",
        "source": "spec_session",
        "source_detail": "Read-only; logs to query_log.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-2: scans -------------------------------

    "run_motor_scan": {
        "long_description": (
            "Absolute motor scan (ascan). Commonly used for alignment "
            "diagnostics where the motor absolute range matters."
        ),
        "python_func": "spec_cmd.call('ascan', [motor, start, end, npoints, count_time], justification)",
        "spec_command": "ascan <motor> <start> <end> <npoints> <count_time>",
        "output": "JSON: {ok, action_id, scan_number, file_name}",
        "source": "spec_session",
        "source_detail": "Produces a new #S block in the current SPEC data file.",
        "depends_on": [],
    },
    "run_motor_scan_relative": {
        "long_description": (
            "Delta scan (dscan) centered on the motor's current "
            "position. Preferred for per-sample fine-tuning."
        ),
        "python_func": "spec_cmd.call('dscan', [motor, delta_start, delta_end, npoints, count_time], justification)",
        "spec_command": "dscan <motor> <delta_start> <delta_end> <npoints> <count_time>",
        "output": "JSON: {ok, action_id, scan_number, file_name}",
        "source": "spec_session",
        "source_detail": "Produces a new #S block; leaves motor at end position (or peak/cen if followed up).",
        "depends_on": ["read_motor_position"],
    },
    "run_xas": {
        "long_description": (
            "Element-specific XAS scan (<element>_xas). Guards: beam "
            "must be present, count_time ≤ 60 s, n_reps ≤ 20."
        ),
        "python_func": "spec_cmd.call('xas', [element, count_time, n_reps, emission_ev?], justification)",
        "spec_command": "<element>_xas <count_time> <n_reps> [<emission_ev>]",
        "output": "JSON: {ok, action_id, scans_started}",
        "source": "spec_session",
        "source_detail": "Gated by get_beam_status; each rep writes its own #S block.",
        "depends_on": ["get_beam_status", "select_element"],
    },
    "run_emiss_scan": {
        "long_description": (
            "Element-specific emission-energy scan (<element>_cee). "
            "Requires an emission_ev; filter is an optional 0-255 bitmask."
        ),
        "python_func": "spec_cmd.call('emiss_scan', [element, count_time, n_reps, emission_ev, filter], justification)",
        "spec_command": "<element>_cee <count_time> <n_reps> <emission_ev> <filter>",
        "output": "JSON: {ok, action_id, scans_started}",
        "source": "spec_session",
        "source_detail": "Similar guards to run_xas.",
        "depends_on": ["get_beam_status", "select_element"],
    },

    # ---------- Autonomy tools — CAT-3: beamline configuration --------------

    "mv_energy": {
        "long_description": (
            "Move incident energy. Does NOT enable tracking — if you "
            "want the ID gap to follow the mono, call `tracking 1` "
            "(not currently exposed as a tool) before invoking this, "
            "or use run_align_shortcut / a dedicated macro."
        ),
        "python_func": "spec_cmd.call('mv_energy', [energy_ev], justification)",
        "spec_command": "umv energy <energy_ev>",
        "output": "JSON: {ok, action_id, energy_ev}",
        "source": "spec_session",
        "source_detail": "Plain absolute-move on the energy motor; may block on gap ownership if tracking is already on.",
        "depends_on": ["request_gap_ownership"],
    },
    "shutter": {
        "long_description": (
            "Fast-shutter control. fsopen/fsclose toggle the shutter; "
            "fson/fsoff enable/disable automatic shuttering; optional "
            "delay_s for timed opens."
        ),
        "python_func": "spec_cmd.call('shutter', [command, delay_s?], justification)",
        "spec_command": "<fsopen|fsclose|fson|fsoff> [<delay_s>]",
        "output": "JSON: {ok, action_id}",
        "source": "spec_session",
        "source_detail": "Immediate — no scan context required.",
        "depends_on": [],
    },
    "set_filter": {
        "long_description": (
            "Set the filter motor to a 0-255 bitmask (each bit is one "
            "filter pad). Used to attenuate the beam before high-flux "
            "scans."
        ),
        "python_func": "spec_cmd.call('mv', ['filter', bitmask], justification)",
        "spec_command": "mv filter <bitmask>",
        "output": "JSON: {ok, action_id, bitmask}",
        "source": "spec_session",
        "source_detail": "Internally a motor move.",
        "depends_on": [],
    },
    "safely_remove_filters": {
        "long_description": (
            "Ramp filters out via the XRS-safe macro — avoids the "
            "sample-damage risk of pulling all attenuators at once."
        ),
        "python_func": "spec_cmd.call('safely_remove_filters', [], justification)",
        "spec_command": "safely_remove_filters",
        "output": "JSON: {ok, action_id}",
        "source": "spec_session",
        "source_detail": "Multi-second; issues a stepped set of filter moves.",
        "depends_on": [],
    },
    "set_gain": {
        "long_description": (
            "Set the SRS current amplifier gain on I0/I1/I2. Accepts a "
            "string setting (e.g. '50 nA/V')."
        ),
        "python_func": "spec_cmd.call('set_i0_gain' | 'set_i1_gain' | 'set_i2_gain', [gain_setting], justification)",
        "spec_command": "set_i0_gain | set_i1_gain | set_i2_gain <setting>",
        "output": "JSON: {ok, action_id, gain}",
        "source": "spec_session",
        "source_detail": "The macro chosen depends on the 'which' arg (i0|i1|i2).",
        "depends_on": [],
    },
    "set_vortex_roi": {
        "long_description": (
            "Set the Vortex ROI. 'auto' uses the element default; "
            "'explicit' takes channel + lo_ev/hi_ev."
        ),
        "python_func": "spec_cmd.call('set_vortex_roi', [args...], justification)",
        "spec_command": "vortex_roi auto <channel>  |  vortex_roi <channel> <lo_ev> <hi_ev>",
        "output": "JSON: {ok, action_id, roi}",
        "source": "spec_session",
        "source_detail": "Shapes the fluorescence window around the expected emission line.",
        "depends_on": [],
    },
    "open_data_file": {
        "long_description": (
            "Start a new SPEC data file (newfile). Used per-sample so "
            "each sample's data lives in its own .dat."
        ),
        "python_func": "spec_cmd.call('newfile', [filename], justification)",
        "spec_command": "newfile <filename>",
        "output": "JSON: {ok, action_id, filename}",
        "source": "spec_session",
        "source_detail": "Subsequent scans write into this file until a new one is opened.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-4: alignment fallbacks -----------------

    "run_align_shortcut": {
        "long_description": (
            "Run one of the named diagnostic shortcuts (vvv, hhh, m1m1, "
            "m2m2, ggg, bzbz, bxbx, dmm, beamx, beamz, cm1m1, cm2m2, "
            "beamx_fine, beamz_fine). Each is a single dscan + "
            "post-analysis."
        ),
        "python_func": "spec_cmd.call('run_shortcut', [name], justification)",
        "spec_command": "<shortcut_name>  (one of vvv|hhh|m1m1|m2m2|ggg|bzbz|bxbx|dmm|beamx|beamz|cm1m1|cm2m2)",
        "output": "JSON: {ok, action_id, scan_number}",
        "source": "spec_session",
        "source_detail": "Rejected if 'name' is not in the hard allow-list.",
        "depends_on": [],
    },
    "post_scan_move": {
        "long_description": (
            "After a scan, move the motor to the detected feature: "
            "'cen' (center) or 'peak'. Run this immediately after a "
            "dscan/ascan to land on the best point."
        ),
        "python_func": "spec_cmd.call('cen' | 'peak', [], justification)",
        "spec_command": "cen | peak",
        "output": "JSON: {ok, action_id, final_position}",
        "source": "spec_session",
        "source_detail": "Uses SPEC's built-in CEN/PEAK detection on the last scan.",
        "depends_on": ["run_motor_scan", "run_motor_scan_relative"],
    },

    # ---------- Autonomy tools — CAT-6: beam monitoring ---------------------

    "get_beam_status": {
        "long_description": (
            "Compact snapshot of whether the beam is usable: SPEAR ring "
            "current, BL15 shutter state, gap ownership, and a "
            "beam_good boolean."
        ),
        "python_func": "spec_cmd.call('beam_status', [], justification='')",
        "spec_command": "p beam_status()",
        "output": "JSON: {spear_current_mA, beamline_state, gap_owned, beam_good, reason}",
        "source": "spec_session",
        "source_detail": "Read-only. The SPEC side is a custom function (spec.d/check_beam.mac) that prints an associative array of SPEAR/BL15/gap state.",
        "depends_on": [],
    },
    "get_i0_value": {
        "long_description": (
            "Take a short count (ct <t>) and read the I0 scaler value. "
            "Used as a sanity check before launching a long scan."
        ),
        "python_func": "spec_cmd.call('ct', [count_time]) + spec_cmd.call('p_global', ['S[I0]'])",
        "spec_command": "ct <count_time>   then   p S[I0]",
        "output": "JSON: {ct: {...}, i0: {value}}",
        "source": "spec_session",
        "source_detail": "Two sequential SPEC queries; no action_log rows (read-only).",
        "depends_on": [],
    },
    "request_gap_ownership": {
        "long_description": (
            "Blocking gaprequest — returns when SPEAR grants BL15 "
            "ownership of the ID gap, or when it times out."
        ),
        "python_func": "spec_cmd.call('gaprequest', [], justification)",
        "spec_command": "gaprequest",
        "output": "JSON: {ok, action_id, granted: bool}",
        "source": "spec_session",
        "source_detail": "Required before mv_energy when SPEAR is the gap owner.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-7: run state ---------------------------

    "get_scan_number": {
        "long_description": (
            "Return SPEC's current SCAN_N counter. Use get_current_"
            "datafile separately if you also need the active file name."
        ),
        "python_func": "spec_cmd.call('scan_n', [], justification='')",
        "spec_command": "p SCAN_N",
        "output": "JSON: {value: int}",
        "source": "spec_session",
        "source_detail": "Read-only.",
        "depends_on": [],
    },
    "get_current_datafile": {
        "long_description": (
            "Parsed fon output — lists the active SPEC data file and "
            "log file paths."
        ),
        "python_func": "spec_cmd.call('fon', [], justification='')",
        "spec_command": "fon",
        "output": "JSON: {datafile, logfile}",
        "source": "spec_session",
        "source_detail": "Read-only.",
        "depends_on": [],
    },
    "abort_current_scan": {
        "long_description": (
            "Send Ctrl-C to SPEC to abort whatever is running. Only "
            "call this after confirming a real problem — aborts are "
            "expensive and may leave hardware in a half-state."
        ),
        "python_func": "spec_cmd.call('abort', [], justification)",
        "spec_command": "<Ctrl-C>",
        "output": "JSON: {ok, action_id}",
        "source": "spec_session",
        "source_detail": "Writes to action_log before sending the interrupt.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-8: orchestration (no SPEC) -------------

    "transition_phase": {
        "long_description": (
            "Advance the experiment phase, or request a revert. "
            "Forward moves are gated by machine-checked preconditions; "
            "backward moves require a human approval posted to Slack."
        ),
        "python_func": "orchestrator.phase.transition_phase(experiment_id, target_phase, ...)",
        "spec_command": None,
        "output": "JSON: {allowed, previous_phase, current_phase, preconditions, reason}",
        "source": "autonomy_db",
        "source_detail": "Reads preconditions via action_log + planner snapshot; writes the new phase row.",
        "depends_on": ["get_experiment_plan", "recent_actions"],
    },
    "request_human_intervention": {
        "long_description": (
            "Pause the agent and ask a human to perform a physical "
            "action (crystal install, sample mount, foil insert, "
            "hardware reset, or custom). Posts to Slack and blocks "
            "until staff resolves it from the dashboard or Slack."
        ),
        "python_func": "orchestrator.staff_guidance.coordinator.request_intervention(...)",
        "spec_command": None,
        "output": "JSON: {resolved, note, resolver}",
        "source": "autonomy_db",
        "source_detail": "Intervention row stored in autonomy DB; notification dispatched to Slack bridge.",
        "depends_on": [],
    },
    "post_status_update": {
        "long_description": (
            "Post a high-level progress message to Slack and the "
            "dashboard feed. Informational — does not block or gate "
            "anything."
        ),
        "python_func": "orchestrator.loop.get_orchestrator().slack_status_post(text)",
        "spec_command": None,
        "output": "JSON: {posted}",
        "source": "slack",
        "source_detail": "Also emits a dashboard WebSocket event.",
        "depends_on": [],
    },
    "update_experiment_plan": {
        "long_description": (
            "Replace the live experiment plan JSON wholesale. The "
            "structure is up to the agent, but downstream views expect "
            "a sample_queue + holder_budgets + budget shape."
        ),
        "python_func": "orchestrator.planner.replace_plan(experiment_id, new_plan)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Writes the plan JSON onto the experiment row.",
        "depends_on": ["get_experiment_plan"],
    },
    "record_sample_progress": {
        "long_description": (
            "Update per-sample status (queued/in_progress/done/skipped/"
            "failed), SNR estimate, efficiency verdict, and reps "
            "completed. Preserves the rest of the plan."
        ),
        "python_func": "orchestrator.planner.record_sample_progress(experiment_id, sample_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Patches a single sample row inside the plan JSON.",
        "depends_on": ["analyze_efficiency"],
    },
    "get_experiment_plan": {
        "long_description": (
            "Return the live experiment plan — config, sample queue, "
            "holder budgets, and the beamtime budget."
        ),
        "python_func": "db.autonomy_client.get_experiment_plan(experiment_id)",
        "spec_command": None,
        "output": "JSON: the full plan object",
        "source": "autonomy_db",
        "source_detail": "Read-only query against the autonomy SQLite DB.",
        "depends_on": [],
    },
    "get_remaining_beamtime": {
        "long_description": (
            "Return total / elapsed / remaining beamtime in hours. "
            "Elapsed is computed from the action_log timestamps."
        ),
        "python_func": "orchestrator.planner.snapshot(experiment_id)",
        "spec_command": None,
        "output": "JSON: {total_hours, elapsed_hours, remaining_hours}",
        "source": "autonomy_db",
        "source_detail": "Derives elapsed from the action_log + start time.",
        "depends_on": [],
    },
    "get_staff_guidance": {
        "long_description": (
            "Recent staff/user guidance messages — either typed into "
            "the dashboard guidance panel or posted to Slack."
        ),
        "python_func": "db.autonomy_client.list_guidance(experiment_id, limit)",
        "spec_command": None,
        "output": "JSON array: [{timestamp, author, text}, ...]",
        "source": "autonomy_db",
        "source_detail": "Guidance rows persisted to the autonomy DB.",
        "depends_on": [],
    },
    "list_open_interventions": {
        "long_description": (
            "List pause-for-human requests that are still waiting for "
            "staff to resolve."
        ),
        "python_func": "db.autonomy_client.list_open_interventions(experiment_id)",
        "spec_command": None,
        "output": "JSON array: [{id, kind, detail, created_at}, ...]",
        "source": "autonomy_db",
        "source_detail": "Sibling table to request_human_intervention.",
        "depends_on": ["request_human_intervention"],
    },
    "recent_actions": {
        "long_description": (
            "Most recent action_log entries for the current experiment "
            "— every SPEC-mutating tool call appears here. Also used "
            "by the phase-transition gate to verify prior success."
        ),
        "python_func": "action_log.db.recent_actions(limit, experiment_id)",
        "spec_command": None,
        "output": "JSON array: [{id, timestamp, phase, command, justification, success}, ...]",
        "source": "autonomy_db",
        "source_detail": "Every spec_cmd.call() writes an action_log row.",
        "depends_on": [],
    },
    "set_sample_time_budget": {
        "long_description": (
            "Adjust the time budget for a single sample — change the "
            "per-rep count_time and/or the number of reps. Mode "
            "restricts the change to one of xas or emiss."
        ),
        "python_func": "orchestrator.planner.set_sample_time_budget(experiment_id, sample_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok}",
        "source": "autonomy_db",
        "source_detail": "Also logs a plan_edit audit row.",
        "depends_on": ["get_experiment_plan"],
    },
    "set_holder_time_budget": {
        "long_description": (
            "Set a default per-sample time budget for a whole sample "
            "holder. New samples inherit the default; when "
            "apply_to_existing is true (default), existing samples on "
            "that holder also pick up the change."
        ),
        "python_func": "orchestrator.planner.set_holder_time_budget(experiment_id, holder_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok, samples_updated}",
        "source": "autonomy_db",
        "source_detail": "Stored under plan.holder_budgets; audit-logged as a plan_edit.",
        "depends_on": [],
    },
    "set_beamtime_budget": {
        "long_description": (
            "Set the total beamtime budget (in hours) to an absolute "
            "value. Use this when a new allocation is granted."
        ),
        "python_func": "orchestrator.planner.set_budget(experiment_id, hours_total)",
        "spec_command": None,
        "output": "JSON: {ok, new_total_hours}",
        "source": "autonomy_db",
        "source_detail": "Audit-logged as a plan_edit.",
        "depends_on": [],
    },
    "extend_beamtime_budget": {
        "long_description": (
            "Add (or subtract, with a negative delta) hours to the "
            "beamtime budget. Use this for small adjustments; use "
            "set_beamtime_budget for absolute resets."
        ),
        "python_func": "orchestrator.planner.extend_budget(experiment_id, hours_delta)",
        "spec_command": None,
        "output": "JSON: {ok, new_total_hours}",
        "source": "autonomy_db",
        "source_detail": "Audit-logged as a plan_edit.",
        "depends_on": [],
    },
    "regenerate_plan": {
        "long_description": (
            "Rebuild the sample plan from the DB while preserving "
            "per-sample progress (status, reps_completed, notes) and "
            "user overrides (thresholds, holder_budgets, total budget). "
            "Call this after a sample holder is added or edited."
        ),
        "python_func": "orchestrator.planner.rebuild_plan_preserving_progress(experiment_id, ...)",
        "spec_command": None,
        "output": "JSON: {ok, sample_count}",
        "source": "autonomy_db",
        "source_detail": "Rewrites the plan JSON in place.",
        "depends_on": ["get_experiment_plan"],
    },
}


def extract_inputs(tool_def: dict) -> list[dict]:
    """Flatten a tool's JSONSchema parameters into a UI-friendly list."""
    fn = tool_def.get("function", {})
    params = fn.get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = set(params.get("required", []) or [])
    out: list[dict] = []
    for name, spec in props.items():
        entry = {
            "name": name,
            "type": spec.get("type", ""),
            "required": name in required,
            "description": spec.get("description", ""),
        }
        if "enum" in spec:
            entry["enum"] = spec["enum"]
        if "default" in spec:
            entry["default"] = spec["default"]
        out.append(entry)
    return out


def build_detailed_tool(tool_def: dict, category: str) -> dict:
    """Merge a tool definition with its lineage entry for the UI."""
    fn = tool_def.get("function", {})
    name = fn.get("name", "")
    lineage = TOOL_LINEAGE.get(name, {})
    return {
        "name": name,
        "category": category,
        "description": fn.get("description", ""),
        "long_description": lineage.get("long_description", ""),
        "python_func": lineage.get("python_func", ""),
        "spec_command": lineage.get("spec_command"),
        "sends_spec_command": lineage.get("spec_command") is not None,
        "output": lineage.get("output", ""),
        "source": lineage.get("source", ""),
        "source_detail": lineage.get("source_detail", ""),
        "depends_on": lineage.get("depends_on", []),
        "inputs": extract_inputs(tool_def),
    }
