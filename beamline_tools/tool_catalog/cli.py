"""CLI interface for BeamtimeHero tools.

Provides a discoverable command-line interface that the LLM can explore
progressively via --help flags, conserving context window tokens.

Also serves reference documents on-demand (context files that would
otherwise be loaded into the system prompt).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import shlex
import sys
from pathlib import Path

from beamline_tools.tool_catalog.executor import execute_tool

logger = logging.getLogger(__name__)

# Reference documents — resolved relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

REFERENCE_DOCS = {
    "agent-instructions": {
        "file": ".claude/prompts/base-layer.md",
        "description": "Mandatory base-layer instructions every autonomous agent must follow (steering queue, completion contract, escalation).",
    },
    "cryostat-procedures": {
        "file": ".claude/skills/cryostat-procedures/SKILL.md",
        "description": "Liquid helium cryostat operating procedures and safety rules",
    },
    "changing-energy": {
        "file": ".claude/skills/changing-energy/SKILL.md",
        "description": "Minimal procedure for switching between absorption edges",
    },
    "energy-calibration": {
        "file": ".claude/skills/energy-calibration/SKILL.md",
        "description": "Mono energy calibration via reference foil: edge scan, calibrate_mono, iterate, reset_gap",
    },
    "beamline-alignment": {
        "file": ".claude/skills/beamline-alignment/SKILL.md",
        "description": "Beamline alignment session notes with lessons learned",
    },
    "spectrometer-alignment": {
        "file": ".claude/skills/spectrometer-alignment/SKILL.md",
        "description": "Procedure for aligning the 7-crystal HERFD spectrometer to a chosen emission line",
    },
    "sample-alignment": {
        "file": ".claude/skills/sample-alignment/SKILL.md",
        "description": "Procedure for aligning the cryostat sample holder (per-sample Sx/Sy/Sz + emiss)",
    },
    "sample-data-collection": {
        "file": ".claude/skills/sample-data-collection/SKILL.md",
        "description": "Procedure for collecting HERFD spectra spot-by-spot, with beam-damage and statistics guidance",
    },
    "spec-reference": {
        "file": ".claude/skills/spec-reference/SKILL.md",
        "description": "SPEC protocol reference for BL15-2",
    },
    "user-reference": {
        "file": ".claude/skills/user-reference/SKILL.md",
        "description": "User guide for BL15-2",
    },
}

# Files that should always stay in the system prompt (even in CLI mode)
ALWAYS_IN_PROMPT = {"system_prompt.txt", "experiment_modes.txt"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beamtimehero",
        description="BeamtimeHero CLI — query beamline scans, logs, and reference documents.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- Data query commands ---
    sub.add_parser("get-latest-scan", help="Get the most recently processed scan with metadata and data preview")

    p = sub.add_parser("list-scans", help="List processed scans with metadata")
    p.add_argument("--limit", type=int, default=20, help="Maximum number of scans to list (default: 20)")

    p = sub.add_parser("read-scan", help="Read a processed scan's data and metadata")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")

    # --- Log commands ---
    p = sub.add_parser("get-latest-log-entries", help="Get the most recent entries from beamline control logs")
    p.add_argument("--lines", type=int, default=100, help="Number of log lines to return (default: 100)")

    p = sub.add_parser("search-logs", help="Search beamline control logs for a string or error message")
    p.add_argument("--query", required=True, help="Text to search for in logs")
    p.add_argument("--max-results", type=int, default=50, help="Maximum number of results (default: 50)")

    p = sub.add_parser("list-logs", help="List available log files")
    p.add_argument("--limit", type=int, default=20, help="Maximum number of logs to list (default: 20)")

    # --- Analysis commands ---
    p = sub.add_parser("get-active-counter", help="Identify the active fluorescence/absorption counter for a scan")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")

    p = sub.add_parser("get-scan-deadtime", help="Get dead time (overhead) for a scan")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")

    p = sub.add_parser("normalize-scan", help="Edge-step normalize a scan (divide by I0, then scale pre/post edge)")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")
    p.add_argument("--counter", help="Counter to normalize. Auto-detected if omitted.")
    p.add_argument("--normalize-by", default="I0", help="Counter to divide by before edge-step (default: I0)")

    p = sub.add_parser("average-scans", help="Average all energy scans in a SPEC file after edge-step normalization")
    p.add_argument("--file-name", help="SPEC file name. If omitted, uses the most recent file with >1 energy scan.")
    p.add_argument("--e-min", type=float, help="Lower energy bound (eV) to crop the average to.")
    p.add_argument("--e-max", type=float, help="Upper energy bound (eV) to crop the average to.")
    p.add_argument("--weighting", choices=["equal", "inverse_variance"], default="equal",
                   help="'equal' (default) = unweighted; 'inverse_variance' = SNR-weighted by per-rep baseline noise.")

    p = sub.add_parser("analyze-convergence", help="Check if repeated scans have converged (cosine similarity) on a feature window.")
    p.add_argument("--file-name", help="SPEC file name. If omitted, uses the most recent file.")
    p.add_argument("--e-min", type=float, required=True, help="Lower bound (eV) of feature window.")
    p.add_argument("--e-max", type=float, required=True, help="Upper bound (eV) of feature window.")

    p = sub.add_parser("analyze-efficiency", help="Full scan repetition efficiency report on a feature window.")
    p.add_argument("--file-name", help="SPEC file name. If omitted, uses the most recent file.")
    p.add_argument("--e-min", type=float, required=True, help="Lower bound (eV) of feature window.")
    p.add_argument("--e-max", type=float, required=True, help="Upper bound (eV) of feature window.")
    p.add_argument("--no-poisson-floor", action="store_true",
                   help="Skip the absolute counts-based Poisson floor (faster).")

    p = sub.add_parser("analyze-feature-evolution",
                       help="Per-rep scalar trace + convergence verdict for a feature defined by [e_min, e_max] and a statistic. Publication-quality test.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, required=True, help="Lower bound (eV) of feature window.")
    p.add_argument("--e-max", type=float, required=True, help="Upper bound (eV) of feature window.")
    p.add_argument("--statistic", choices=["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                   default="max", help="Reduction over the window. 'max'=white-line height; 'argmax'=position; 'integral'=area.")
    p.add_argument("--sem-threshold-frac", type=float, default=0.01,
                   help="Target final SEM as fraction of running mean (default 0.01 = 1%%).")
    p.add_argument("--drift-threshold-frac", type=float, default=0.01,
                   help="Target step-to-step running-mean drift fraction.")

    p = sub.add_parser("group-scans-by-spot",
                       help="Cluster a file's scans by sample spot using Sx/Sy/Sz motor positions.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--tol-mm", type=float, default=0.05, help="Position tolerance in mm (default 0.05).")

    p = sub.add_parser("analyze-per-spot",
                       help="Run convergence analysis per spot + report between/within heterogeneity F-statistic.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, help="Lower bound (eV) of feature window.")
    p.add_argument("--e-max", type=float, help="Upper bound (eV) of feature window.")
    p.add_argument("--tol-mm", type=float, default=0.05, help="Position tolerance in mm.")

    # --- Plot commands ---
    p = sub.add_parser("plot-scan", help="Generate a plot of scan data")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")
    p.add_argument("--counter", help="Counter to plot (e.g. I0, vortDT). Auto-detected if omitted.")
    p.add_argument("--normalize-by", help="Counter to normalize by (e.g. I0)")

    p = sub.add_parser("plot-averaged-scans", help="Plot averaged energy scans for multiple samples overlaid")
    p.add_argument("--file-names", required=True, help="JSON array of SPEC file names to compare")

    p = sub.add_parser("plot-scan-stack",
                       help="Overlay all reps of one sample, color-progressed by rep order. Optionally cropped to [e_min, e_max].")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, help="Lower bound (eV).")
    p.add_argument("--e-max", type=float, help="Upper bound (eV).")

    p = sub.add_parser("plot-first-half-vs-second-half",
                       help="Compare first-half vs second-half running averages with SEM bands. Reports max |Δ|/SEM.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, help="Lower bound (eV).")
    p.add_argument("--e-max", type=float, help="Upper bound (eV).")

    p = sub.add_parser("plot-running-average",
                       help="Plot the running average across reps as it accumulates, with final SEM band.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, help="Lower bound (eV).")
    p.add_argument("--e-max", type=float, help="Upper bound (eV).")

    p = sub.add_parser("plot-feature-evolution",
                       help="Plot per-rep scalar over [e_min, e_max] vs rep number with running mean ±SEM.")
    p.add_argument("--file-name", required=True, help="SPEC file name.")
    p.add_argument("--e-min", type=float, required=True, help="Lower bound (eV).")
    p.add_argument("--e-max", type=float, required=True, help="Upper bound (eV).")
    p.add_argument("--statistic", choices=["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                   default="max", help="Reduction over the window.")

    p = sub.add_parser("plot-data", help="General-purpose line chart from data arrays")
    p.add_argument("--x", required=True, help="JSON array of X values")
    p.add_argument("--y", required=True, help="JSON array of Y values")
    p.add_argument("--y2", help="JSON array for optional second series")
    p.add_argument("--y3", help="JSON array for optional third series")
    p.add_argument("--y4", help="JSON array for optional fourth series")
    p.add_argument("--xlabel", help="X-axis label")
    p.add_argument("--ylabel", help="Y-axis label")
    p.add_argument("--title", help="Plot title")
    p.add_argument("--labels", help="JSON array of legend labels")

    # --- File commands ---
    p = sub.add_parser("list-files", help="List non-SPEC files in the scan directory (macros, configs, etc.)")
    p.add_argument("--pattern", default="*", help="Glob pattern to filter files (default: *)")

    p = sub.add_parser("read-file", help="Read a text file from the scan directory")
    p.add_argument("--path", required=True, help="File path relative to scan directory (e.g. run01.mac)")

    p = sub.add_parser("write-summary", help="Save a conversation summary as a .txt file in the scan directory")
    p.add_argument("--content", required=True, help="The summary text to write")

    p = sub.add_parser("write-macro", help="Save an edited macro as a new .mac file in the scan directory")
    p.add_argument("--original-name", required=True, help="Original macro filename (e.g. run01.mac)")
    p.add_argument("--content", required=True, help="The edited macro content")

    p = sub.add_parser("save-plan", help="Save a markdown plan into the project's logs/plans/ directory")
    p.add_argument("--filename", required=True,
                   help="Plan filename. Must end in .md; no path separators or traversal.")
    p.add_argument("--content", help="Plan markdown body (use this OR --content-file)")
    p.add_argument("--content-file", help="Path to a file whose contents become the plan body")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite an existing plan with the same filename")

    # --- SPEC config commands ---
    sub.add_parser("get-motor-config", help="Get SPEC motor configuration (controller, steps, mnemonic, name)")
    sub.add_parser("get-counter-config", help="Get SPEC counter configuration (controller, channel, mnemonic, name)")

    # --- Reference command ---
    p = sub.add_parser("reference", help="Look up beamline reference documents")
    p.add_argument("doc_name", nargs="?", help="Name of the reference document to display")
    p.add_argument("--list", action="store_true", dest="list_docs", help="List all available reference documents")

    return parser


def _cli_name_to_tool(name: str) -> str:
    """Convert CLI command name (kebab-case) to tool name (snake_case for executor)."""
    return name.replace("-", "_")


def _run_reference(args: argparse.Namespace) -> str:
    """Handle the 'reference' subcommand."""
    if args.list_docs or not args.doc_name:
        lines = ["Available reference documents:", ""]
        for name, info in REFERENCE_DOCS.items():
            lines.append(f"  {name:25s} {info['description']}")
        lines.append("")
        lines.append("Usage: beamtimehero reference <doc-name>")
        return "\n".join(lines)

    doc_name = args.doc_name
    if doc_name not in REFERENCE_DOCS:
        return f"Unknown reference: '{doc_name}'. Use 'beamtimehero reference --list' to see available documents."

    doc_path = PROJECT_ROOT / REFERENCE_DOCS[doc_name]["file"]
    try:
        return doc_path.read_text()
    except FileNotFoundError:
        return f"Reference file not found: {doc_path}"


def run_cli(command_str: str) -> tuple[str, list[str]]:
    """Parse and execute a CLI command string.

    Returns:
        (output_text, images_b64): Text output and any base64 plot images.
    """
    # Strip the 'beamtimehero' prefix if present
    cmd = command_str.strip()
    if cmd.startswith("beamtimehero"):
        cmd = cmd[len("beamtimehero"):].strip()

    parser = _build_parser()

    # Capture --help output instead of exiting. Use tokenized check so command
    # names containing "-h" (e.g. plot-first-half-vs-second-half) don't false-trigger.
    try:
        _tokens = shlex.split(cmd) if cmd else []
    except ValueError:
        _tokens = []
    _wants_help = (not cmd) or ("--help" in _tokens) or ("-h" in _tokens)
    if _wants_help:
        buf = io.StringIO()
        parser.print_help(buf) if not cmd or cmd in ("--help", "-h") else None
        if cmd and cmd not in ("--help", "-h"):
            # Try to get subcommand help
            subcmd = _tokens[0] if _tokens else ""
            try:
                sub_parser = parser._subparsers._group_actions[0].choices.get(subcmd)
                if sub_parser:
                    sub_parser.print_help(buf)
                else:
                    parser.print_help(buf)
            except Exception:
                parser.print_help(buf)
        help_text = buf.getvalue()
        if help_text:
            return help_text, []

    try:
        args = parser.parse_args(shlex.split(cmd))
    except SystemExit:
        # argparse calls sys.exit on errors; capture that
        buf = io.StringIO()
        parser.print_help(buf)
        return buf.getvalue(), []

    if not args.command:
        buf = io.StringIO()
        parser.print_help(buf)
        return buf.getvalue(), []

    # Reference command is handled directly
    if args.command == "reference":
        return _run_reference(args), []

    # Map CLI args to tool arguments
    tool_name = _cli_name_to_tool(args.command)
    tool_args = {}

    if tool_name == "list_scans":
        tool_args["limit"] = args.limit
    elif tool_name == "read_scan":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
    elif tool_name == "get_latest_log_entries":
        tool_args["lines"] = args.lines
    elif tool_name == "search_logs":
        tool_args["query"] = args.query
        tool_args["max_results"] = args.max_results
    elif tool_name == "list_logs":
        tool_args["limit"] = args.limit
    elif tool_name == "get_active_counter":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
    elif tool_name == "get_scan_deadtime":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
    elif tool_name == "normalize_scan":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
        if args.counter:
            tool_args["counter"] = args.counter
        tool_args["normalize_by"] = args.normalize_by
    elif tool_name == "average_scans":
        if args.file_name:
            tool_args["file_name"] = args.file_name
        if args.e_min is not None:
            tool_args["e_min"] = args.e_min
        if args.e_max is not None:
            tool_args["e_max"] = args.e_max
        tool_args["weighting"] = args.weighting
    elif tool_name in ("analyze_convergence", "analyze_efficiency"):
        if args.file_name:
            tool_args["file_name"] = args.file_name
        tool_args["e_min"] = args.e_min
        tool_args["e_max"] = args.e_max
        if tool_name == "analyze_efficiency":
            tool_args["include_poisson_floor"] = not args.no_poisson_floor
    elif tool_name == "analyze_feature_evolution":
        tool_args["file_name"] = args.file_name
        tool_args["e_min"] = args.e_min
        tool_args["e_max"] = args.e_max
        tool_args["statistic"] = args.statistic
        tool_args["sem_threshold_frac"] = args.sem_threshold_frac
        tool_args["drift_threshold_frac"] = args.drift_threshold_frac
    elif tool_name == "group_scans_by_spot":
        tool_args["file_name"] = args.file_name
        tool_args["tol_mm"] = args.tol_mm
    elif tool_name == "analyze_per_spot":
        tool_args["file_name"] = args.file_name
        if args.e_min is not None:
            tool_args["e_min"] = args.e_min
        if args.e_max is not None:
            tool_args["e_max"] = args.e_max
        tool_args["tol_mm"] = args.tol_mm
    elif tool_name == "plot_averaged_scans":
        tool_args["file_names"] = json.loads(args.file_names)
    elif tool_name == "plot_scan":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
        if args.counter:
            tool_args["counter"] = args.counter
        if args.normalize_by:
            tool_args["normalize_by"] = args.normalize_by
    elif tool_name in ("plot_scan_stack", "plot_first_half_vs_second_half", "plot_running_average"):
        tool_args["file_name"] = args.file_name
        if args.e_min is not None:
            tool_args["e_min"] = args.e_min
        if args.e_max is not None:
            tool_args["e_max"] = args.e_max
    elif tool_name == "plot_feature_evolution":
        tool_args["file_name"] = args.file_name
        tool_args["e_min"] = args.e_min
        tool_args["e_max"] = args.e_max
        tool_args["statistic"] = args.statistic
    elif tool_name == "plot_data":
        tool_args["x"] = json.loads(args.x)
        tool_args["y"] = json.loads(args.y)
        if args.y2:
            tool_args["y2"] = json.loads(args.y2)
        if args.y3:
            tool_args["y3"] = json.loads(args.y3)
        if args.y4:
            tool_args["y4"] = json.loads(args.y4)
        if args.xlabel:
            tool_args["xlabel"] = args.xlabel
        if args.ylabel:
            tool_args["ylabel"] = args.ylabel
        if args.title:
            tool_args["title"] = args.title
        if args.labels:
            tool_args["labels"] = json.loads(args.labels)

    # New tools handled directly (not routed through executor)
    if tool_name == "list_files":
        return execute_tool(tool_name, {"pattern": args.pattern})
    elif tool_name == "read_file":
        return execute_tool(tool_name, {"path": args.path})
    elif tool_name == "write_summary":
        return execute_tool(tool_name, {"content": args.content})
    elif tool_name == "write_macro":
        return execute_tool(tool_name, {
            "original_name": args.original_name,
            "content": args.content,
        })
    elif tool_name == "save_plan":
        if args.content is not None and args.content_file is not None:
            return "Error: pass either --content or --content-file, not both.", []
        if args.content_file is not None:
            try:
                content = Path(args.content_file).read_text(encoding="utf-8")
            except OSError as e:
                return f"Error reading --content-file: {e}", []
        elif args.content is not None:
            content = args.content
        else:
            return "Error: --content or --content-file is required.", []
        return execute_tool(tool_name, {
            "filename": args.filename,
            "content": content,
            "overwrite": args.overwrite,
        })
    elif tool_name in ("get_motor_config", "get_counter_config"):
        return execute_tool(tool_name, {})
    return execute_tool(tool_name, tool_args)
