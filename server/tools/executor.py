"""Tool executor — dispatches tool calls to blmcp implementations.

Returns (result_text, images_b64) for each tool invocation.
"""
from __future__ import annotations

import json
import logging

import matplotlib
matplotlib.use("Agg")

from blmcp import tools as bl_tools
from bldata_analysis.plotting import fig_to_base64

logger = logging.getLogger(__name__)


def execute_tool(name: str, arguments: dict) -> tuple[str, list[str]]:
    """Execute a named tool with arguments.

    Returns:
        (result_text, images_b64): JSON result string and list of base64 PNG images.
    """
    images_b64: list[str] = []

    # Autonomy tools take priority when registered.
    try:
        from tools.autonomy_tools import AUTONOMY_DISPATCH  # lazy to avoid cycles
    except Exception:
        AUTONOMY_DISPATCH = {}

    if name in AUTONOMY_DISPATCH:
        try:
            text, imgs = AUTONOMY_DISPATCH[name](arguments or {})
            return text, list(imgs or [])
        except Exception as e:
            logger.error("Autonomy tool %s failed: %s", name, e, exc_info=True)
            return f"Tool error ({name}): {e}", []

    try:
        if name == "get_latest_scan":
            result = bl_tools.get_latest_scan()
            return (
                json.dumps(result, indent=2) if result else "No processed scans found.",
                images_b64,
            )

        elif name == "list_scans":
            result = bl_tools.list_scans(limit=arguments.get("limit", 20))
            return json.dumps(result, indent=2), images_b64

        elif name == "read_scan":
            result = bl_tools.read_scan(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
            )
            return (
                json.dumps(result, indent=2) if result else "Scan not found.",
                images_b64,
            )

        elif name == "get_latest_log_entries":
            result = bl_tools.get_latest_log_entries(
                lines=arguments.get("lines", 100),
            )
            return (
                json.dumps(result, indent=2) if result else "No log files found.",
                images_b64,
            )

        elif name == "search_logs":
            result = bl_tools.search_logs(
                arguments.get("query", ""),
                max_results=arguments.get("max_results", 50),
            )
            return json.dumps(result, indent=2), images_b64

        elif name == "list_logs":
            result = bl_tools.list_logs(limit=arguments.get("limit", 20))
            return json.dumps(result, indent=2), images_b64

        elif name == "get_active_counter":
            result = bl_tools.get_active_counter(
                arguments.get("file_name", ""),
                arguments.get("scan_number", 1),
            )
            return (
                json.dumps(result, indent=2) if result else "Scan not found.",
                images_b64,
            )

        elif name == "get_scan_deadtime":
            result = bl_tools.get_scan_deadtime(
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
            result = bl_tools.edge_step_normalize_scan(
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
                result = bl_tools.average_energy_scans(file_name=file_name)
            else:
                result = bl_tools.average_latest_energy_scans()
            return json.dumps(result, indent=2), images_b64

        elif name == "analyze_convergence":
            result = bl_tools.analyze_scan_convergence(
                file_name=arguments.get("file_name"),
            )
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "analyze_efficiency":
            result = bl_tools.analyze_scan_efficiency(
                file_name=arguments.get("file_name"),
            )
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "plot_averaged_scans":
            file_names = arguments.get("file_names", [])
            if not file_names:
                return "Error: file_names array must not be empty.", images_b64
            fig, summary = bl_tools.plot_averaged_scans_overlay(file_names)
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_scan":
            fig, summary = bl_tools.plot_scan(
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
            from bldata_analysis.plotting import plt

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
            import local_data
            result = local_data.list_files(pattern=arguments.get("pattern", "*"))
            if not result:
                return "No files found in scan directory.", images_b64
            return json.dumps(result, indent=2), images_b64

        elif name == "read_file":
            import local_data
            content = local_data.read_file(arguments.get("path", ""))
            return content, images_b64

        elif name == "write_summary":
            import local_data
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"beamtimehero_conversation_summary_{ts}.txt"
            rel_path = local_data.write_file(filename, arguments.get("content", ""))
            return f"Summary saved: {rel_path}", images_b64

        elif name == "write_macro":
            import local_data
            from datetime import datetime
            original = arguments.get("original_name", "macro")
            # Strip .mac extension if present to build new name
            base = original.rsplit(".mac", 1)[0] if original.endswith(".mac") else original
            ts = datetime.now().strftime("%Y-%m-%d")
            filename = f"{base}_heroic_{ts}.mac"
            rel_path = local_data.write_file(filename, arguments.get("content", ""))
            return f"Edited macro saved: {rel_path}", images_b64

        elif name == "get_motor_config":
            from spec_config import get_motor_config
            return get_motor_config(), images_b64

        elif name == "get_counter_config":
            from spec_config import get_counter_config
            return get_counter_config(), images_b64

        elif name == "spec_command":
            from spec_client import send_spec_command
            result = send_spec_command(arguments.get("command", ""))
            return result, images_b64

        else:
            return f"Unknown tool: {name}", images_b64

    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Tool error ({name}): {e}", images_b64
