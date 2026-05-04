"""Tool executor — dispatches tool calls to underlying beamline_tools modules.

Returns (result_text, images_b64) for each tool invocation.
"""
from __future__ import annotations

import json
import logging

import matplotlib
matplotlib.use("Agg")

from beamline_tools.spec_data import scans as scan_data
from beamline_tools.spec_data import plotting
from beamline_tools.spec_data.plotting import fig_to_base64
from beamline_tools.spec_logs import log_reader

logger = logging.getLogger(__name__)


# External packages (orchestration) register their tool functions here
# via `beamline_tools.tool_catalog.register(definition, fn)` at import time.
_EXTRA_DISPATCH: dict[str, object] = {}


def register_dispatch(name: str, fn) -> None:
    _EXTRA_DISPATCH[name] = fn


def _analyze_with(file_name, analyzer):
    """Shared shape for convergence and efficiency: load normalized arrays, run analyzer, attach context."""
    try:
        combined, file_name, counter, used_scans = scan_data.get_normalized_scan_arrays(file_name)
    except ValueError as e:
        return {"error": str(e)}
    if len(used_scans) < 2:
        return {"error": f"Need at least 2 scans, found {len(used_scans)}."}
    scan_data_2d = combined.dropna().values.T.tolist()
    result = analyzer(scan_data_2d)
    if "error" in result:
        return result
    result["file_name"] = file_name
    result["active_counter"] = counter
    result["scan_numbers"] = used_scans
    return result


def execute_tool(name: str, arguments: dict) -> tuple[str, list[str]]:
    """Execute a named tool with arguments.

    Returns:
        (result_text, images_b64): JSON result string and list of base64 PNG images.
    """
    images_b64: list[str] = []

    # Base autonomy tools (CAT-0..CAT-7) + any externally registered ones.
    try:
        from beamline_tools.tool_catalog.autonomy_tools import AUTONOMY_DISPATCH  # lazy to avoid cycles
    except Exception:
        AUTONOMY_DISPATCH = {}

    dispatch = {**AUTONOMY_DISPATCH, **_EXTRA_DISPATCH}

    if name in dispatch:
        try:
            text, imgs = dispatch[name](arguments or {})
            return text, list(imgs or [])
        except Exception as e:
            logger.error("Autonomy tool %s failed: %s", name, e, exc_info=True)
            return f"Tool error ({name}): {e}", []

    try:
        if name == "get_latest_scan":
            entries = scan_data.list_processed_scans(limit=1)
            if not entries:
                return "No processed scans found.", images_b64
            entry = entries[0]
            df = scan_data.read_processed_scan(entry["file_name"], entry["scan_number"])
            if df is not None:
                entry["data_preview"] = df.head(10).to_string()
                entry["counters"] = list(df.columns)
            return json.dumps(entry, indent=2), images_b64

        elif name == "list_scans":
            result = scan_data.list_processed_scans(limit=arguments.get("limit", 20))
            return json.dumps(result, indent=2), images_b64

        elif name == "read_scan":
            file_name = arguments.get("file_name", "")
            scan_number = arguments.get("scan_number", 1)
            meta = scan_data.get_scan_metadata(file_name, scan_number)
            if not meta:
                return "Scan not found.", images_b64
            df = scan_data.read_processed_scan(file_name, scan_number)
            if df is not None:
                meta["data"] = df.to_string()
            return json.dumps(meta, indent=2), images_b64

        elif name == "get_latest_log_entries":
            result = log_reader.get_latest_log_entries(lines=arguments.get("lines", 100))
            return (
                json.dumps(result, indent=2) if result else "No log files found.",
                images_b64,
            )

        elif name == "search_logs":
            result = log_reader.search_logs(
                arguments.get("query", ""),
                max_results=arguments.get("max_results", 50),
            )
            return json.dumps(result, indent=2), images_b64

        elif name == "list_logs":
            result = log_reader.list_logs(limit=arguments.get("limit", 20))
            return json.dumps(result, indent=2), images_b64

        elif name == "get_active_counter":
            result = scan_data.get_active_counter(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
            )
            return (
                json.dumps(result, indent=2) if result else "Scan not found.",
                images_b64,
            )

        elif name == "get_scan_deadtime":
            result = scan_data.get_scan_deadtime(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
            )
            return (
                json.dumps(result, indent=2, default=str)
                if result
                else "Scan not found or no dead time data available.",
                images_b64,
            )

        elif name == "normalize_scan":
            result = scan_data.edge_step_normalize_scan(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
                counter=arguments.get("counter"),
                normalize_by=arguments.get("normalize_by", "I0"),
            )
            return (
                json.dumps(result, indent=2) if result else "Scan not found.",
                images_b64,
            )

        elif name == "average_scans":
            file_name = arguments.get("file_name")
            if file_name:
                result = scan_data.average_energy_scans(file_name=file_name)
            else:
                result = scan_data.average_latest_energy_scans()
            return json.dumps(result, indent=2), images_b64

        elif name == "analyze_convergence":
            from beamline_tools.generic_data.cosine_similarity import analyze_scan_quality
            result = _analyze_with(arguments.get("file_name"), analyze_scan_quality)
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "analyze_efficiency":
            from beamline_tools.experiment_planning.scan_efficiency import analyze_scan_efficiency
            result = _analyze_with(arguments.get("file_name"), analyze_scan_efficiency)
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "plot_averaged_scans":
            file_names = arguments.get("file_names", [])
            if not file_names:
                return "Error: file_names array must not be empty.", images_b64
            fig, summary = plotting.plot_averaged_scans_overlay(file_names)
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_scan":
            fig, summary = plotting.plot_scan(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
                counter=arguments.get("counter"),
                normalize_by=arguments.get("normalize_by"),
            )
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_data":
            from beamline_tools.spec_data.plotting import plt

            x = arguments.get("x", [])
            series = [arguments.get("y", [])]
            for key in ("y2", "y3", "y4"):
                s = arguments.get(key)
                if s:
                    series.append(s)

            if not x or not series[0]:
                return "Error: x and y arrays must not be empty.", images_b64

            for i, y_vals in enumerate(series):
                if len(y_vals) != len(x):
                    return (
                        f"Error: series {i+1} has {len(y_vals)} points but x has {len(x)}.",
                        images_b64,
                    )

            labels = arguments.get("labels", [])
            xlabel = arguments.get("xlabel", "")
            ylabel = arguments.get("ylabel", "")
            title = arguments.get("title", "")

            fig, ax = plt.subplots(figsize=(10, 6))
            for i, y_vals in enumerate(series):
                label = labels[i] if i < len(labels) else None
                ax.plot(x, y_vals, linewidth=1.2, label=label)
            if xlabel:
                ax.set_xlabel(xlabel)
            if ylabel:
                ax.set_ylabel(ylabel)
            if title:
                ax.set_title(title, fontsize=11)
            if labels:
                ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            fig.tight_layout()

            images_b64.append(fig_to_base64(fig))
            plt.close(fig)

            summary = f"Plot generated: {title or 'untitled'} ({len(x)} points, {len(series)} series)"
            return summary, images_b64

        elif name == "list_files":
            from beamline_tools.spec_data import local_data
            result = local_data.list_files(pattern=arguments.get("pattern", "*"))
            if not result:
                return "No files found in scan directory.", images_b64
            return json.dumps(result, indent=2), images_b64

        elif name == "read_file":
            from beamline_tools.spec_data import local_data
            content = local_data.read_file(arguments.get("path", ""))
            return content, images_b64

        elif name == "write_summary":
            from beamline_tools.spec_data import local_data
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"beamtimehero_conversation_summary_{ts}.txt"
            rel_path = local_data.write_file(filename, arguments.get("content", ""))
            return f"Summary saved: {rel_path}", images_b64

        elif name == "write_macro":
            from beamline_tools.spec_data import local_data
            from datetime import datetime
            original = arguments.get("original_name", "macro")
            # Strip .mac extension if present to build new name
            base = original.rsplit(".mac", 1)[0] if original.endswith(".mac") else original
            ts = datetime.now().strftime("%Y-%m-%d")
            filename = f"{base}_heroic_{ts}.mac"
            rel_path = local_data.write_file(filename, arguments.get("content", ""))
            return f"Edited macro saved: {rel_path}", images_b64

        elif name == "get_motor_config":
            from beamline_tools.spec_data.spec_config import get_motor_config
            return get_motor_config(), images_b64

        elif name == "get_counter_config":
            from beamline_tools.spec_data.spec_config import get_counter_config
            return get_counter_config(), images_b64

        elif name == "spec_command":
            from beamline_tools.spec_control import spec_cmd, transport
            cmd = arguments.get("command", "")
            if not cmd.strip():
                return "error: empty command", images_b64
            if not transport.reserve(action_id="raw-spec", command=cmd):
                return "error: SPEC is busy", images_b64
            try:
                dr = spec_cmd.dispatch(cmd, timeout_s=60)
            finally:
                transport.release(output=None, errored=False)
            return (dr.output if dr.ok else f"error: {dr.error}"), images_b64

        elif name == "evaluate_spec_macro":
            from beamline_tools.spec_eval import evaluate_spec_macro
            result = evaluate_spec_macro(
                macro=arguments.get("macro", ""),
                preload=arguments.get("preload"),
                timeout_s=arguments.get("timeout_s", 30),
            )
            return json.dumps(result, indent=2), images_b64

        else:
            return f"Unknown tool: {name}", images_b64

    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Tool error ({name}): {e}", images_b64
