"""Tool executor — dispatches tool calls to underlying beamline_tools modules.

Returns (result_text, images_b64) for each tool invocation.
"""
from __future__ import annotations

import json
import logging

import matplotlib
matplotlib.use("Agg")
import numpy as np

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


def _analyze_with(
    file_name,
    analyzer,
    e_min=None,
    e_max=None,
    scan_numbers=None,
    include_raw_counts: bool = False,
):
    """Shared shape for convergence and efficiency: load normalized arrays
    (optionally windowed to [e_min, e_max] and/or restricted to scan_numbers),
    run analyzer, attach context.

    If include_raw_counts is True, also load the raw active-counter rate stack
    over the SAME energy window and pass it to the analyzer as
    raw_counts_per_point. The analyzer must accept that kwarg.
    """
    try:
        combined, file_name, counter, used_scans = scan_data.get_normalized_scan_arrays(
            file_name, e_min=e_min, e_max=e_max, scan_numbers=scan_numbers,
        )
    except ValueError as e:
        return {"error": str(e)}
    if len(used_scans) < 2:
        return {"error": f"Need at least 2 scans, found {len(used_scans)}."}

    # Drop rows with NaN in any scan to keep a common grid
    combined_clean = combined.dropna()
    scan_data_2d = combined_clean.values.T.tolist()

    kwargs = {}
    if include_raw_counts:
        try:
            raw_combined, _, _, raw_used = scan_data.get_raw_counter_arrays(
                file_name, scan_numbers=used_scans,
            )
            # Align raw counts to the same energy grid as the windowed normalized stack
            raw_aligned = raw_combined.reindex(combined_clean.index)
            count_times = raw_combined.attrs.get("count_times", [1.0] * len(raw_used))
            # Convert rate -> per-rep total counts at each point: rate * count_time
            raw_total = raw_aligned.values * np.array(count_times)[np.newaxis, :]
            kwargs["raw_counts_per_point"] = raw_total.T.tolist()
        except Exception as e:
            logger.warning("Could not load raw counts for Poisson floor: %s", e)

    result = analyzer(scan_data_2d, **kwargs) if kwargs else analyzer(scan_data_2d)
    if "error" in result:
        return result
    result["file_name"] = file_name
    result["active_counter"] = counter
    result["scan_numbers"] = used_scans
    if e_min is not None and e_max is not None:
        result["energy_window"] = [e_min, e_max]
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
            trimmed = {
                k: entry[k]
                for k in ("file_name", "scan_number", "scan_command", "date_time", "num_points")
                if k in entry
            }
            return json.dumps(trimmed, indent=2), images_b64

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
            e_min = arguments.get("e_min")
            e_max = arguments.get("e_max")
            weighting = arguments.get("weighting", "equal")
            if file_name:
                result = scan_data.average_energy_scans(
                    file_name=file_name, e_min=e_min, e_max=e_max, weighting=weighting,
                )
            else:
                result = scan_data.average_latest_energy_scans(
                    e_min=e_min, e_max=e_max, weighting=weighting,
                )
            return json.dumps(result, indent=2), images_b64

        elif name == "analyze_convergence":
            from beamline_tools.generic_data.cosine_similarity import analyze_scan_quality
            result = _analyze_with(
                arguments.get("file_name"),
                analyze_scan_quality,
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
            )
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "analyze_efficiency":
            from beamline_tools.experiment_planning.scan_efficiency import analyze_scan_efficiency
            result = _analyze_with(
                arguments.get("file_name"),
                analyze_scan_efficiency,
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
                include_raw_counts=bool(arguments.get("include_poisson_floor", True)),
            )
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "analyze_feature_evolution":
            from beamline_tools.experiment_planning.scan_features import (
                analyze_feature_evolution,
            )
            file_name = arguments.get("file_name")
            e_min = arguments.get("e_min")
            e_max = arguments.get("e_max")
            statistic = arguments.get("statistic", "max")
            sem_target = float(arguments.get("sem_threshold_frac", 0.01))
            drift_target = float(arguments.get("drift_threshold_frac", 0.01))
            if e_min is None or e_max is None:
                return (
                    json.dumps({
                        "error": "analyze_feature_evolution requires e_min and e_max (numeric eV bounds)."
                    }, indent=2),
                    images_b64,
                )
            try:
                combined, file_name, counter, used_scans = (
                    scan_data.get_normalized_scan_arrays(file_name)
                )
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2), images_b64
            combined = combined.dropna()
            energy = combined.index.values.tolist()
            scan_2d = combined.values.T.tolist()
            result = analyze_feature_evolution(
                scan_2d, energy, e_min, e_max, statistic=statistic,
                sem_threshold_frac=sem_target, drift_threshold_frac=drift_target,
            )
            if isinstance(result, dict):
                result.setdefault("file_name", file_name)
                result.setdefault("active_counter", counter)
                result.setdefault("scan_numbers", used_scans)
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "group_scans_by_spot":
            file_name = arguments.get("file_name")
            tol_mm = float(arguments.get("tol_mm", 0.05))
            if not file_name:
                return (
                    json.dumps({"error": "file_name is required."}, indent=2),
                    images_b64,
                )
            result = scan_data.group_scans_by_spot(file_name, tol_mm=tol_mm)
            return json.dumps(result, indent=2, default=str), images_b64

        elif name == "analyze_per_spot":
            from beamline_tools.experiment_planning.scan_efficiency import (
                analyze_scan_efficiency,
            )
            from beamline_tools.experiment_planning.scan_features import (
                heterogeneity_f_statistic,
            )
            file_name = arguments.get("file_name")
            e_min = arguments.get("e_min")
            e_max = arguments.get("e_max")
            tol_mm = float(arguments.get("tol_mm", 0.05))
            if not file_name:
                return (
                    json.dumps({"error": "file_name is required."}, indent=2),
                    images_b64,
                )
            grouping = scan_data.group_scans_by_spot(file_name, tol_mm=tol_mm)
            if "error" in grouping:
                return json.dumps(grouping, indent=2), images_b64

            per_spot_results = []
            per_spot_arrays = []
            for spot in grouping["spots"]:
                if spot["spot_id"] == -1 or spot["n_scans"] < 2:
                    continue
                try:
                    combined, _, counter, used = scan_data.get_normalized_scan_arrays(
                        file_name,
                        e_min=e_min,
                        e_max=e_max,
                        scan_numbers=spot["scan_numbers"],
                    )
                except ValueError as e:
                    per_spot_results.append({
                        "spot_id": spot["spot_id"],
                        "error": str(e),
                    })
                    continue
                clean = combined.dropna()
                arr_2d = clean.values.T.tolist()
                per_spot_arrays.append(arr_2d)
                eff = analyze_scan_efficiency(arr_2d)
                per_spot_results.append({
                    "spot_id": spot["spot_id"],
                    "center": spot["center"],
                    "scan_numbers": spot["scan_numbers"],
                    "n_scans": spot["n_scans"],
                    "verdict": eff.get("verdict"),
                    "cv_mean_pct": eff.get("cv_mean_pct"),
                    "final_convergence": eff.get("convergence", {}).get(
                        "cumulative_convergence", [None]
                    )[-1],
                })

            heterogeneity = None
            if len(per_spot_arrays) >= 2:
                # Trim each spot's stack to the minimum n_points across spots
                min_pts = min(len(a[0]) for a in per_spot_arrays)
                trimmed = [[row[:min_pts] for row in a] for a in per_spot_arrays]
                heterogeneity = heterogeneity_f_statistic(trimmed)

            return (
                json.dumps({
                    "file_name": file_name,
                    "energy_window": [e_min, e_max] if (e_min is not None and e_max is not None) else None,
                    "tol_mm": tol_mm,
                    "n_spots_analyzed": len(per_spot_results),
                    "per_spot": per_spot_results,
                    "heterogeneity": heterogeneity,
                }, indent=2, default=str),
                images_b64,
            )

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

        elif name == "plot_scan_stack":
            fig, summary = plotting.plot_scan_stack(
                arguments.get("file_name", ""),
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
            )
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_first_half_vs_second_half":
            fig, summary = plotting.plot_first_half_vs_second_half(
                arguments.get("file_name", ""),
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
            )
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_running_average":
            fig, summary = plotting.plot_running_average(
                arguments.get("file_name", ""),
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
            )
            if fig:
                images_b64.append(fig_to_base64(fig))
                import matplotlib.pyplot as plt
                plt.close(fig)
            return summary, images_b64

        elif name == "plot_feature_evolution":
            fig, summary = plotting.plot_feature_evolution(
                arguments.get("file_name", ""),
                e_min=arguments.get("e_min"),
                e_max=arguments.get("e_max"),
                statistic=arguments.get("statistic", "max"),
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

        elif name == "save_plan":
            import re as _re
            from beamline_tools.config import PLANS_DIR
            filename = (arguments.get("filename") or "").strip()
            content = arguments.get("content") or ""
            overwrite = bool(arguments.get("overwrite", False))
            if not _re.match(r"^[A-Za-z0-9_\-.]+\.md$", filename) or filename.startswith("."):
                return json.dumps({
                    "ok": False,
                    "error": (
                        "filename must match ^[A-Za-z0-9_\\-.]+\\.md$ and not start with "
                        "'.' (no path separators, traversal, or hidden files)"
                    ),
                }), images_b64
            target = (PLANS_DIR / filename).resolve()
            try:
                target.relative_to(PLANS_DIR.resolve())
            except ValueError:
                return json.dumps({
                    "ok": False,
                    "error": f"resolved path escapes PLANS_DIR: {target}",
                }), images_b64
            existed = target.exists()
            if existed and not overwrite:
                return json.dumps({
                    "ok": False,
                    "error": f"file exists: {filename}; pass overwrite=true to replace",
                }), images_b64
            target.write_text(content, encoding="utf-8")
            return json.dumps({
                "ok": True,
                "path": str(target),
                "bytes": len(content.encode("utf-8")),
                "overwrote": existed,
            }, indent=2), images_b64

        elif name == "get_motor_config":
            from beamline_tools.spec_data.spec_config import get_motor_config
            return get_motor_config(), images_b64

        elif name == "get_counter_config":
            from beamline_tools.spec_data.spec_config import get_counter_config
            return get_counter_config(), images_b64

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
