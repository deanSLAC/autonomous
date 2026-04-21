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

from tools.executor import execute_tool

logger = logging.getLogger(__name__)

# Context files that are available as CLI references instead of system prompt
CONTEXT_DIR = Path(__file__).parent.parent.parent / "context"

REFERENCE_DOCS = {
    "cryostat-procedures": {
        "file": "cryostat_procedures.txt",
        "description": "Liquid helium cryostat operating procedures and safety rules",
    },
    "spec-commands": {
        "file": "BL15-2_SPEC_Reference.txt",
        "description": "SPEC beamline control software command reference",
    },
    "user-operations": {
        "file": "BL15-2_user_reference.txt",
        "description": "BL15-2 user operations quick reference guide",
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

    p = sub.add_parser("analyze-convergence", help="Check if repeated scans have converged (cosine similarity metrics)")
    p.add_argument("--file-name", help="SPEC file name. If omitted, uses the most recent file.")

    p = sub.add_parser("analyze-efficiency", help="Full scan repetition efficiency report: convergence, CV, optimal count, verdict")
    p.add_argument("--file-name", help="SPEC file name. If omitted, uses the most recent file.")

    # --- Plot commands ---
    p = sub.add_parser("plot-scan", help="Generate a plot of scan data")
    p.add_argument("--file-name", required=True, help="The SPEC source file name")
    p.add_argument("--scan-number", type=int, required=True, help="The scan number within the file")
    p.add_argument("--counter", help="Counter to plot (e.g. I0, vortDT). Auto-detected if omitted.")
    p.add_argument("--normalize-by", help="Counter to normalize by (e.g. I0)")

    p = sub.add_parser("plot-averaged-scans", help="Plot averaged energy scans for multiple samples overlaid")
    p.add_argument("--file-names", required=True, help="JSON array of SPEC file names to compare")

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

    # --- SPEC config commands ---
    sub.add_parser("get-motor-config", help="Get SPEC motor configuration (controller, steps, mnemonic, name)")
    sub.add_parser("get-counter-config", help="Get SPEC counter configuration (controller, channel, mnemonic, name)")

    # --- SPEC command ---
    p = sub.add_parser("spec-command", help="Send a command to the running SPEC session (whitelisted commands only)")
    p.add_argument("--cmd", required=True, dest="spec_cmd", help="Command to send: wa, pwd, fon, or get_S (for get_S, also run get-counter-config to map S[] indices to counter names)")

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

    doc_path = CONTEXT_DIR / REFERENCE_DOCS[doc_name]["file"]
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

    # Capture --help output instead of exiting
    if not cmd or "--help" in cmd or "-h" in cmd:
        buf = io.StringIO()
        parser.print_help(buf) if not cmd or cmd in ("--help", "-h") else None
        if cmd and cmd not in ("--help", "-h"):
            # Try to get subcommand help
            parts = shlex.split(cmd)
            subcmd = parts[0] if parts else ""
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
    elif tool_name in ("analyze_convergence", "analyze_efficiency"):
        if args.file_name:
            tool_args["file_name"] = args.file_name
    elif tool_name == "plot_averaged_scans":
        tool_args["file_names"] = json.loads(args.file_names)
    elif tool_name == "plot_scan":
        tool_args["file_name"] = args.file_name
        tool_args["scan_number"] = args.scan_number
        if args.counter:
            tool_args["counter"] = args.counter
        if args.normalize_by:
            tool_args["normalize_by"] = args.normalize_by
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
    elif tool_name in ("get_motor_config", "get_counter_config"):
        return execute_tool(tool_name, {})
    elif tool_name == "spec_command":
        return execute_tool(tool_name, {"command": args.spec_cmd})

    return execute_tool(tool_name, tool_args)
