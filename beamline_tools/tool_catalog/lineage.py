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
        "python_func": "spec_data.scans.list_processed_scans(limit=1) + read_processed_scan(...)",
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
        "python_func": "spec_data.scans.list_processed_scans(limit=20)",
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
        "python_func": "spec_data.scans.get_scan_metadata(file_name, scan_number) + read_processed_scan(...)",
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
        "python_func": "spec_logs.log_reader.get_latest_log_entries(lines=100)",
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
        "python_func": "spec_logs.log_reader.search_logs(query, max_results=50)",
        "spec_command": None,
        "output": "JSON array: [{log_file, line_number, line}, ...]",
        "source": "spec_logfile",
        "source_detail": "Scans all files under BL_LOGS_DIR via spec_logs.log_reader.",
        "depends_on": [],
    },
    "list_logs": {
        "long_description": (
            "List the available log files in BL_LOGS_DIR with their sizes "
            "and modification times."
        ),
        "python_func": "spec_logs.log_reader.list_logs(limit=20)",
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
        "python_func": "spec_data.scans.get_active_counter(file_name, scan_number)",
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
        "python_func": "spec_data.scans.get_scan_deadtime(file_name, scan_number)",
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
        "python_func": "spec_data.scans.edge_step_normalize_scan(file_name, scan_number, counter, normalize_by)",
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
        "python_func": "spec_data.scans.average_energy_scans(file_name)  |  average_latest_energy_scans()",
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
        "python_func": "generic_data.cosine_similarity.analyze_scan_quality (via spec_data.scans.get_normalized_scan_arrays)",
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
        "python_func": "experiment_planning.scan_efficiency.analyze_scan_efficiency (via spec_data.scans.get_normalized_scan_arrays)",
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
        "python_func": "spec_data.plotting.plot_scan(file_name, scan_number, counter, normalize_by)",
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
        "python_func": "spec_data.plotting.plot_averaged_scans_overlay(file_names)",
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
        "python_func": "matplotlib.pyplot (in-process, via spec_data.plotting)",
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
        "python_func": "spec_data.local_data.list_files(pattern)",
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
        "python_func": "spec_data.local_data.read_file(path)",
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
        "python_func": "spec_data.local_data.write_file(beamtimehero_conversation_summary_<ts>.txt, content)",
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
        "python_func": "spec_data.local_data.write_file(<original>_heroic_<date>.mac, content)",
        "spec_command": None,
        "output": "Relative path of the new .mac file",
        "source": "filesystem",
        "source_detail": "Writes into BL_SCAN_DIR alongside existing macros.",
        "depends_on": ["read_file"],
    },
    "save_plan": {
        "long_description": (
            "Persist a markdown plan into the project's logs/plans/ directory. "
            "Used at the start of multi-step tasks (typically beamline "
            "optimization) to record the step-by-step plan the agent "
            "intends to follow, so future sessions can review what was "
            "attempted and why. Filenames are validated against a strict "
            "allow-list and writes are confined to PLANS_DIR — no path "
            "traversal, no overwriting unless explicitly requested."
        ),
        "python_func": "PLANS_DIR.joinpath(filename).write_text(content)  (with regex + path-confinement checks)",
        "spec_command": None,
        "output": "JSON: {ok, path, bytes, overwrote}",
        "source": "filesystem",
        "source_detail": "Writes into PLANS_DIR (./logs/plans/ under the project root).",
        "depends_on": [],
    },
    "get_motor_config": {
        "long_description": (
            "Return SPEC's motor table: per-motor controller, steps/unit, "
            "slew rate, flags, and mnemonic. The motor index (MOTnnn) "
            "maps directly to the A[] array in SPEC."
        ),
        "python_func": "spec_data.spec_config.get_motor_config()",
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
        "python_func": "spec_data.spec_config.get_counter_config()",
        "spec_command": None,
        "output": "Plain-text table (one row per counter)",
        "source": "spec_config",
        "source_detail": "Parses the SPEC config file on disk.",
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
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {crystals, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {element, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Pulls the target geometry from the experiment plan.",
        "depends_on": ["get_plan"],
    },
    "peak_mono_pitch": {
        "long_description": (
            "LVDT-driven piezo optimization of the 2nd mono crystal "
            "pitch. Used as a fallback or pre-scan tune-up."
        ),
        "python_func": "spec_cmd.call('peak_mono_pitch', [], justification)",
        "spec_command": "peak_mono_pitch",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Short macro; typically runs in seconds.",
        "depends_on": [],
    },
    "calibrate_mono": {
        "long_description": (
            "Standard mono calibration: dscan energy ±15 eV over a "
            "reference foil, find the inflection, then call "
            "calibrate_mono + reset_gap. The tabulated edge energy must "
            "be within 5 eV of the current energy."
        ),
        "python_func": "spec_cmd.call('calibrate_mono', [tabulated_edge_ev], justification)",
        "spec_command": "calibrate_mono <tabulated_edge_ev>",
        "output": "JSON: {ok, kind, action_id, result: {tabulated_ev, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {motor, target, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {motor, delta, raw, elapsed_s}, elapsed_s}",
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
        "spec_command": "wm <motor>",
        "output": "JSON: {ok, kind, result: {value, raw}}",
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
        "output": "JSON: {ok, kind, result: {positions: {motor: value, ...}, raw}}",
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
        "output": "JSON: {ok, kind, action_id, result: {motor, start, end, npoints, count_time, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {motor, delta_start, delta_end, npoints, count_time, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Produces a new #S block; leaves motor at end position (or peak/cen if followed up).",
        "depends_on": ["read_motor_position"],
    },
    "run_diagonal_scan": {
        "long_description": (
            "Two-motor diagonal scan (SPEC's d2scan) — both motors move "
            "in lockstep over the same delta range and number of points. "
            "Used during sample alignment to map a sample's footprint in "
            "the Sx/Sy plane (the d2scan in auto_sample_align's per-sample "
            "boundary detection). Default range is ±8 if delta_lo / "
            "delta_hi aren't provided. The dispatcher checks motor1 "
            "against the phase allow-list; the wrapper additionally "
            "validates motor2 before dispatch."
        ),
        "python_func": (
            "spec_cmd.call('d2scan', "
            "[motor1, delta_lo, delta_hi, motor2, delta_lo, delta_hi, "
            "npoints, count_time], justification)"
        ),
        "spec_command": (
            "d2scan <motor1> <delta_lo> <delta_hi> "
            "<motor2> <delta_lo> <delta_hi> <npoints> <count_time>"
        ),
        "output": (
            "JSON: {ok, kind, action_id, "
            "result: {motor1, delta_lo1, delta_hi1, motor2, delta_lo2, "
            "delta_hi2, npoints, count_time, raw, elapsed_s}, elapsed_s}"
        ),
        "source": "spec_session",
        "source_detail": "d2scan defined in standard.mac:1126 via _angle_scan_prep.",
        "depends_on": ["read_motor_position"],
    },
    "fit_emission_peak": {
        "long_description": (
            "Fit the most recent (or specified) emission scan with the "
            "lab's Pseudo-Voigt+skew model and return the suggested "
            "emission energy in eV. Wraps the SPEC `get_HERFD_energy` "
            "macro, which shells out to "
            "/usr/local/projects/HERFD_energy/get_HERFD_energy.py and "
            "prints `Suggested new emission value is <eV>`. Does NOT "
            "move the spectrometer — the agent decides whether/how to "
            "apply the value (e.g. via a follow-up emiss move)."
        ),
        "python_func": (
            "spec_cmd.call('get_HERFD_energy', [scan_number?], justification)"
        ),
        "spec_command": "get_HERFD_energy [<scan_number>]",
        "output": (
            "JSON: {ok, kind, action_id, "
            "result: {emission_ev, raw, elapsed_s}, elapsed_s}"
        ),
        "source": "spec_session",
        "source_detail": (
            "Defined in get_HERFD_energy.mac:2; reads the active DATAFILE "
            "and the current PLOT_SEL counter, then runs the external "
            "fitter."
        ),
        "depends_on": ["run_motor_scan_relative"],
    },
    "run_xas": {
        "long_description": (
            "Calls the SPEC run_xas macro, which dispatches to <El>_xas "
            "for the element set by the prior select_element. "
            "Args: cntSec (null→1 s), nbrScan (null→1), emission "
            "(0 → emiss motor unchanged), nbrFilter (<0 → filter motor unchanged)."
        ),
        "python_func": "spec_cmd.call('run_xas', [count_time, n_reps, emission_ev, filter], justification)",
        "spec_command": "run_xas <cntSec> <nbrScan> <emission> <nbrFilter>",
        "output": "JSON: {ok, kind, action_id, result: {count_time, n_reps, emission_ev, filter, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Element-side dispatch lives in run_xas.mac; each rep writes its own #S block.",
        "depends_on": ["get_beam_status", "select_element"],
    },
    "run_emiss_scan": {
        "long_description": (
            "Element-specific emission-energy scan (<element>_cee). "
            "Requires an emission_ev; filter is an optional 0-255 bitmask."
        ),
        "python_func": "spec_cmd.call('emiss_scan', [element, count_time, n_reps, emission_ev, filter], justification)",
        "spec_command": "<element>_cee <count_time> <n_reps> <emission_ev> <filter>",
        "output": "JSON: {ok, kind, action_id, result: {element, count_time, n_reps, emission_ev, filter, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {target_ev, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {command, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {motor, target, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {gain, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "The macro chosen depends on the 'which' arg (i0|i1|i2).",
        "depends_on": [],
    },
    "set_vortex_roi": {
        "long_description": (
            "Set the Vortex ROI. mode='auto': bounds ±200 eV around the emission "
            "line for channel (1=vortDT, 3=vortDT2 for a second emission peak). "
            "mode='explicit': set channel + lo_ev/hi_ev in eV directly."
        ),
        "python_func": "spec_cmd.call('set_vortex_roi', [args...], justification)",
        "spec_command": "vortex_roi auto <channel>  |  vortex_roi <channel> <lo_ev> <hi_ev>",
        "output": "JSON: {ok, kind, action_id, result: {args, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {filename, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Subsequent scans write into this file until a new one is opened.",
        "depends_on": [],
    },

    "plotselect": {
        "long_description": (
            "Select which counter SPEC uses for plotting during scans. "
            "Use I1 for alignment optimization (downstream signal), "
            "vortDT for fluorescence, I0 for upstream flux monitoring. "
            "Does not affect data collection — only the live plot display."
        ),
        "python_func": "spec_cmd.call('plotselect', [counter], justification)",
        "spec_command": "plotselect <counter>",
        "output": "JSON: {ok, kind, action_id, result: {counter, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Instantaneous SPEC command; no scan context required.",
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
        "output": "JSON: {ok, kind, action_id, result: {name, raw, elapsed_s}, elapsed_s}",
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
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Uses SPEC's built-in CEN/PEAK detection on the last scan.",
        "depends_on": ["run_motor_scan", "run_motor_scan_relative"],
    },

    # ---------- Autonomy tools — CAT-5: beam-diagnostic tool ----------------

    "mv_pinhole": {
        "long_description": (
            "Move the sample stage so the diagnostic-tool pinhole is in "
            "the beam. Sx/Sy/Sz/Sr are driven to the pinhole pose, plus "
            "any active pinhole_offset."
        ),
        "python_func": "spec_cmd.call('mvpinhole', [], justification)",
        "spec_command": "mvpinhole",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac via rdef; pose updates whenever update_pinhole_pos is called.",
        "depends_on": [],
    },
    "mv_plastic": {
        "long_description": (
            "Move the sample stage so the diagnostic-tool plastic "
            "scatterer is in the beam. Used to generate elastic scatter "
            "for XES spectrometer alignment."
        ),
        "python_func": "spec_cmd.call('mvplastic', [], justification)",
        "spec_command": "mvplastic",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac via rdef.",
        "depends_on": [],
    },
    "mv_knife_clear": {
        "long_description": (
            "Move the sample stage so the knife-edge blades are clear of "
            "the beam. Fast move, but the diagnostic body may still "
            "partially clip the beam to I1 — prefer mv_knife_out before "
            "trusting I1 for upstream-optic alignment."
        ),
        "python_func": "spec_cmd.call('mvknifeclear', [], justification)",
        "spec_command": "mvknifeclear",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac via rdef.",
        "depends_on": [],
    },
    "mv_knife_out": {
        "long_description": (
            "Move the sample stage so the entire diagnostic tool is "
            "fully out of the beam path. Slower than mv_knife_clear "
            "(large Sr rotation) but unambiguous: nothing diagnostic-"
            "related is in the beam."
        ),
        "python_func": "spec_cmd.call('mvknifewayout', [], justification)",
        "spec_command": "mvknifewayout",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac via rdef; sets Sr=80 so the full diagnostic body clears the beam.",
        "depends_on": [],
    },
    "measure_beam_size": {
        "long_description": (
            "Knife-edge scan to measure horizontal and vertical beam "
            "FWHM. Multi-minute. Removes filters, ensures DATAFILE="
            "alignment, runs centered knife-edge scans on Sx and Sz, "
            "stores results in the global beamsize[] array. Each axis "
            "supports 'big' (large mm-scale beam) or 'small' (~50um "
            "focused) modes — wrong mode produces artifacts."
        ),
        "python_func": "spec_cmd.call('measure_beam_size', [mode_x, mode_z], justification)",
        "spec_command": "measure_beam_size <mode_x> <mode_z>",
        "output": "JSON: {ok, kind, action_id, result: {mode_x, mode_z, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:250; chains center_knife_edge_x/z + beamx/beamz scans.",
        "depends_on": [],
    },
    "zero_pinhole": {
        "long_description": (
            "Center the beam on the diagnostic-tool pinhole, then zero "
            "(or apply the configured pinhole_offset to) Tz/Sz/Bz/Tx/Sx/"
            "Bx. Multi-minute. Refuses to run if the table is not in "
            "its usual position (Tz < 15.5 with no offset configured)."
        ),
        "python_func": "spec_cmd.call('zero_pinhole', [], justification)",
        "spec_command": "zero_pinhole",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:467; chains find_pinhole + center_on_pinhole + table/sample/B-stage zeroing.",
        "depends_on": [],
    },
    "small_beam": {
        "long_description": (
            "Set the KB-mirror benders to the small-beam (~50um focused) "
            "preset. Moves m1ubend/m1dbend/m2ubend/m2dbend to the "
            "configured small-beam values and tags both beamsize_mode "
            "axes as 'small'."
        ),
        "python_func": "spec_cmd.call('smallbeam', [], justification)",
        "spec_command": "smallbeam",
        "output": "JSON: {ok, kind, action_id, result: {raw, mode: 'small', elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:68.",
        "depends_on": [],
    },
    "big_beam": {
        "long_description": (
            "Set the KB-mirror benders to the big-beam (mm-scale, "
            "standard) preset. Moves m1ubend/m1dbend/m2ubend/"
            "m2dbend to the configured big-beam values and tags both "
            "beamsize_mode axes as 'big'."
        ),
        "python_func": "spec_cmd.call('bigbeam', [], justification)",
        "spec_command": "bigbeam",
        "output": "JSON: {ok, kind, action_id, result: {raw, mode: 'big', elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:78.",
        "depends_on": [],
    },
    "xtal_align": {
        "long_description": (
            "Recalibrate the crystal-motor encoder zero. Runs a dscan "
            "over the crystal motor, peaks on the diffraction feature, "
            "then redefines the current encoder reading to the original "
            "(pre-scan) value. The motor stays in place; its zero is "
            "now anchored on the peak. Used after a crystal swap or "
            "when the crystal feature has drifted."
        ),
        "python_func": "spec_cmd.call('xtalalign', [], justification)",
        "spec_command": "xtalalign",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:87; valid_dscan crystal + peak + set crystal <old>.",
        "depends_on": [],
    },
    "reset_gap": {
        "long_description": (
            "Recalibrate the undulator gap encoder zero. Runs ggg (gap "
            "dscan), peaks on the flux maximum, then redefines the gap "
            "encoder so the original (pre-scan) reading is preserved on "
            "the new peak. Run ONCE at the end of an energy-calibration "
            "sequence -- iterating reset_gap during calibration fights "
            "the calibrate_mono loop."
        ),
        "python_func": "spec_cmd.call('reset_gap', [], justification)",
        "spec_command": "reset_gap",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:95; ggg + peak + set gap <old>.",
        "depends_on": [],
    },
    "set_m2_stripe": {
        "long_description": (
            "Move M2 (m2vert) to the appropriate stripe for the supplied "
            "incident energy. Branches: <4500 eV -> Rh (with a warning), "
            "4500-6200 eV -> Si (m2vert=9.69), >=6200 eV -> Rh "
            "(m2vert=-3.5). Use whenever the incident energy crosses a "
            "stripe boundary."
        ),
        "python_func": "spec_cmd.call('m2_stripe', [energy_ev], justification)",
        "spec_command": "m2_stripe",
        "output": "JSON: {ok, kind, action_id, result: {energy_ev, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in beam_diagnostics.mac:103; dispatches to m2_Rh or m2_Si (umv m2vert).",
        "depends_on": [],
    },
    "get_anchor": {
        "long_description": (
            "Read the current tracking-anchor state from the SPEC "
            "session: energy + m1vert + Tz at anchor time, the "
            "constituent m1vert1/m1vert2/Tz1/Tz2 motor positions, the "
            "crystal id, and the SPEAR steering offset stored at "
            "anchor time. Also reports whether SPEAR has visibly "
            "drifted (monvtra moved since anchoring) and whether the "
            "crystal set has changed (which makes the anchor invalid "
            "for the current geometry). Read-only — no justification "
            "required."
        ),
        "python_func": "spec_cmd.call('get_anchor', [], justification='')",
        "spec_command": "get_anchor",
        "output": (
            "JSON: {ok, kind, result: {energy, m1vert, m1vert1, m1vert2, "
            "Tz, Tz1, Tz2, crystal, spear_steering, spear_drift, "
            "crystal_changed, raw}}"
        ),
        "source": "spec_session",
        "source_detail": "Defined in tracking.mac:249.",
        "depends_on": [],
    },
    "set_anchor": {
        "long_description": (
            "Capture mono/m1vert/m1vert1/m1vert2/Tz/Tz1/Tz2 (plus "
            "monvtra for SPEAR steering) as the tracking-anchor "
            "reference, and persist to anchor.cfg + a timestamped "
            "backup. The anchor is the fixed beam-position pivot that "
            "energy-tracking uses to keep the focused beam on the "
            "sample as the mono Bragg angle changes. Call once the "
            "beam is aligned at a known reference energy."
        ),
        "python_func": "spec_cmd.call('set_anchor', [], justification)",
        "spec_command": "set_anchor",
        "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in tracking.mac:268; calls save_anchor → /usr/local/lib/spec.d/anchor.cfg + ANCHOR_DIR backup.",
        "depends_on": [],
    },
    "tracking": {
        "long_description": (
            "Toggle energy-tracking on (1) or off (0). With tracking "
            "enabled, every energy move also drives m1vert and Tz so "
            "the focused beam stays at the anchor position as the mono "
            "Bragg angle changes. Requires set_anchor first -- without "
            "an anchor, tracking has no reference and the beam will "
            "drift. Disable before procedures that need m1vert/Tz "
            "free of automatic motion (e.g. KB-mirror alignment)."
        ),
        "python_func": "spec_cmd.call('tracking', ['0'|'1'], justification)",
        "spec_command": "tracking <0|1>",
        "output": "JSON: {ok, kind, action_id, result: {enabled, raw, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Defined in tracking.mac:139; flips global _TRACKING which gates the _track() hook on energy moves.",
        "depends_on": ["set_anchor"],
    },

    # ---------- Autonomy tools — CAT-6: beam monitoring ---------------------

    "get_beam_size": {
        "long_description": (
            "Return the last-measured horizontal and vertical beam FWHM "
            "(mm) and the current beam-size mode (big/small/unknown) for "
            "each axis. Read-only — reads SPEC globals set by "
            "measure_beam_size / beamx / beamz."
        ),
        "python_func": "spec_cmd.call('wbeamsize', [], justification='')",
        "spec_command": "wbeamsize",
        "output": "JSON: {ok, kind, result: {horizontal_fwhm_mm, vertical_fwhm_mm, horizontal_mode, vertical_mode, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only. Defined in beam_diagnostics.mac; prints beamsize[] and beamsize_mode[] globals.",
        "depends_on": [],
    },
    "get_beam_status": {
        "long_description": (
            "Compact snapshot of whether the beam is usable: SPEAR ring "
            "current, BL15 shutter state, gap ownership, and a "
            "beam_good boolean."
        ),
        "python_func": "spec_cmd.call('beam_status', [], justification='')",
        "spec_command": "p beam_status()",
        "output": "JSON: {ok, kind, result: {spear_current_ma, beamline_state, gap_owned, beam_good, reason, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only. The SPEC side is a custom function (spec.d/check_beam.mac) that prints an associative array of SPEAR/BL15/gap state.",
        "depends_on": [],
    },
    "get_counts": {
        "long_description": (
            "Count for the specified time (default 0.5 s) and return all "
            "counter values as a {name: value} map."
        ),
        "python_func": "spec_cmd.call('ct', [count_time], justification='')",
        "spec_command": "ct <count_time>",
        "output": "JSON: {ok, kind, result: {counters: {name: value, ...}, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only; logs to query_log.",
        "depends_on": [],
    },
    "get_counter": {
        "long_description": (
            "Count for the specified time (default 0.5 s) and return one "
            "specific counter's value. Runs ct and extracts the named counter."
        ),
        "python_func": "spec_cmd.call('ct', [count_time], justification='') → filter by counter name",
        "spec_command": "ct <count_time>",
        "output": "JSON: {ok, kind, result: {value, counter, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only; logs to query_log.",
        "depends_on": ["get_counts"],
    },
    "request_gap_ownership": {
        "long_description": (
            "Blocking gaprequest — returns when SPEAR grants BL15 "
            "ownership of the ID gap, or when it times out."
        ),
        "python_func": "spec_cmd.call('gaprequest', [], justification)",
        "spec_command": "gaprequest",
        "output": "JSON: {ok, kind, action_id, result: {raw, granted, elapsed_s}, elapsed_s}",
        "source": "spec_session",
        "source_detail": "Required before mv_energy when SPEAR is the gap owner.",
        "depends_on": [],
    },

    # ---------- Autonomy tools — CAT-7: run state ---------------------------

    "get_element": {
        "long_description": (
            "Return the value of the SPEC variable ELEMENT — the "
            "currently active element for the experiment."
        ),
        "python_func": "spec_cmd.call('p_element', [], justification='')",
        "spec_command": "p ELEMENT",
        "output": "JSON: {ok, kind, result: {element, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only. Prints the ELEMENT global variable.",
        "depends_on": [],
    },
    "get_scan_number": {
        "long_description": (
            "Return SPEC's current SCAN_N counter. Use get_current_"
            "datafile separately if you also need the active file name."
        ),
        "python_func": "spec_cmd.call('scan_n', [], justification='')",
        "spec_command": "p SCAN_N",
        "output": "JSON: {ok, kind, result: {value, raw}}",
        "source": "spec_session",
        "source_detail": "Read-only.",
        "depends_on": [],
    },
    "get_current_datafile": {
        "long_description": (
            "Returns the active SPEC data file path via the DATAFILE global."
        ),
        "python_func": "spec_cmd.call('p_datafile', [], justification='')",
        "spec_command": "p DATAFILE",
        "output": "JSON: {ok, kind, result: {raw}}",
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
        "output": "JSON: {ok, kind, action_id}",
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
        "depends_on": ["get_plan", "recent_actions"],
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
        "depends_on": ["get_plan"],
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
    "get_plan": {
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
    "get_experiment_config": {
        "long_description": (
            "Return the operator-entered experiment configuration "
            "from the DB: experiment-level settings (mono crystal, "
            "beam, mirrors, sample env, data path), the configured "
            "elements, and every sample holder with its samples. "
            "This is the canonical record of what the user entered "
            "in the /config form — distinct from get_plan, which "
            "returns the live planner state."
        ),
        "python_func": (
            "session.get(Experiment, experiment_id) + ExperimentElement "
            "+ SampleHolder + SamplePosition rows"
        ),
        "spec_command": None,
        "output": "JSON: {experiment, elements[], sample_holders[{samples[]}]}",
        "source": "autonomy_db",
        "source_detail": "Read-only query against the autonomy SQLite DB.",
        "depends_on": [],
    },
    "get_remaining_beamtime": {
        "long_description": (
            "Hours from now until Experiment.end_time. Returns "
            "{remaining_hours, end_time}; both null if end_time has "
            "not been set yet."
        ),
        "python_func": "orchestrator.planner.snapshot(experiment_id)",
        "spec_command": None,
        "output": "JSON: {remaining_hours, end_time}",
        "source": "autonomy_db",
        "source_detail": "end_time lives on Experiment; this tool just subtracts now().",
        "depends_on": ["set_experiment_end_time"],
    },
    "set_experiment_end_time": {
        "long_description": (
            "Set Experiment.end_time. The planner's remaining-beamtime "
            "math is end_time - now(). Accepts ISO-8601 end_time or "
            "hours_from_now."
        ),
        "python_func": "orchestrator.plan_store.session.set_experiment_end_time(...)",
        "spec_command": None,
        "output": "JSON: {ok, end_time, remaining_hours}",
        "source": "autonomy_db",
        "source_detail": "Audit-logged as a plan_edit.",
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
        "depends_on": ["get_plan"],
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
        "depends_on": ["get_plan"],
    },
    "get_scans_since_last_plan_update": {
        "long_description": (
            "Return the list of CollectionScan rows whose timestamp is "
            "newer than the live ExperimentPlan.updated_at. Lets the "
            "Planner see exactly what data has been collected since the "
            "plan was last revised."
        ),
        "python_func": (
            "plan_store.session.get_collection_scans_since(experiment_id, "
            "ExperimentPlan.updated_at)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, plan_updated_at, count, scans:[{scan_number, sample_id, sample_name, technique, filter_setting, count_time, timestamp, spec_datafile}]}",
        "source": "autonomy_db",
        "source_detail": "Joins CollectionScan with SamplePosition for sample_name.",
        "depends_on": ["get_plan", "update_experiment_plan"],
    },
    "get_scans_for_active_sample": {
        "long_description": (
            "Return every CollectionScan for the currently-active "
            "sample. Active = plan_json.active_sample_id (if set) else "
            "the lowest-queue-order sample whose status is not 'done' "
            "or 'skipped'. `sample_id` overrides the auto-detect."
        ),
        "python_func": (
            "plan_store.session.get_collection_scans_for_sample(active_sample_id)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, sample_id, sample_name, count, scans:[...]}",
        "source": "autonomy_db",
        "source_detail": "Reads plan_json to detect the active sample, then joins SamplePosition.",
        "depends_on": ["get_plan"],
    },
    "upload_sample_survey_results": {
        "long_description": (
            "Persist Sample-Surveyor outputs to SamplePosition rows. "
            "filter_count overwrites xas_filter (so Data Collection picks "
            "it up); counts_per_sec is recorded as the survey reference "
            "rate. survey_energy_ev / notes are stored as-is. "
            "survey_completed_at is set to now()."
        ),
        "python_func": "plan_store.session.submit_survey_results(results)",
        "spec_command": None,
        "output": "JSON: {ok, updated:[sample_ids], count}",
        "source": "autonomy_db",
        "source_detail": (
            "Mutates SamplePosition.xas_filter, .survey_counts_per_sec, "
            ".survey_energy_ev, .survey_notes, .survey_completed_at."
        ),
        "depends_on": [],
    },
    "get_comprehensive_collection_plan": {
        "long_description": (
            "Return the per-sample/spot/filter/n_scans plan that Data "
            "Collection executes against. Synthesizes from "
            "ExperimentPlan.plan_json + SamplePosition rows + survey "
            "results (xas_filter, survey_counts_per_sec). "
            "planned_scans_total comes from plan_json's per-sample "
            "entry when set, falling back to xas_reps."
        ),
        "python_func": (
            "session.get(SampleHolder, ...) + SamplePosition rows + "
            "plan_store.client.get_experiment_plan(experiment_id)"
        ),
        "spec_command": None,
        "output": (
            "JSON: {ok, sample_holder_id, sample_holder_name, samples:["
            "{sample_id, sample_name, element_symbol, total_spots, "
            "filter_count, count_time, n_reps, counts_per_sec, "
            "planned_time_s, planned_scans_total}]}"
        ),
        "source": "autonomy_db",
        "source_detail": "Read-only synthesis across SampleHolder, SamplePosition, ExperimentPlan.",
        "depends_on": ["get_plan", "get_experiment_config"],
    },

    "record_completed_scan": {
        "long_description": (
            "Insert a CollectionScan row keyed by sample_id + "
            "scan_number after each successful run_xas (or sibling "
            "technique). Called by the Data Collection / Sample "
            "Surveyor agents between scans so the Planner's "
            "convergence analysis and the orchestrator's plan summary "
            "(recent_plots lookup) can see what's been collected. "
            "Auto-fills sample_id / scan_number / spec_datafile from "
            "the active context when omitted."
        ),
        "python_func": (
            "plan_store.session.create_collection_scan(experiment_id, "
            "sample_id, technique, scan_number, spec_datafile, "
            "filter_setting, count_time)"
        ),
        "spec_command": None,
        "output": "JSON: {ok, scan_id, sample_id, sample_name, scan_number, technique}",
        "source": "autonomy_db",
        "source_detail": (
            "Inserts a CollectionScan row keyed by sample_id + "
            "scan_number; agents call this after each successful "
            "run_xas to make scans queryable for plan summaries and "
            "convergence analysis."
        ),
        "depends_on": ["get_scan_number", "get_current_datafile"],
    },

    # ---------- Sandbox evaluation -----------------------------------------

    "evaluate_spec_macro": {
        "long_description": (
            "Run a SPEC macro in a disposable, network-isolated Docker "
            "container and return the execution log. Use to validate "
            "macros you authored or edited, or to reproduce a SPEC error "
            "in isolation. Each call is a cold start with no state from "
            "prior runs. The container has read-only access to production "
            "beamline macros but no network and no host devices — it "
            "cannot affect the live beamline. Always read the log even on "
            "ok=True; SPEC sometimes exits 0 despite warnings."
        ),
        "python_func": "spec_eval.evaluate_spec_macro(macro, preload, timeout_s)",
        "spec_command": None,
        "output": "JSON: {ok, exit_code, timed_out, log, duration_s, run_id, error}",
        "source": "tool_chain",
        "source_detail": (
            "POSTs to the spec-eval API (default http://127.0.0.1:5005) "
            "which runs the macro in a disposable Docker container with "
            "sim-mode SPEC. Override URL via SPEC_EVAL_URL env var."
        ),
        "depends_on": [],
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
