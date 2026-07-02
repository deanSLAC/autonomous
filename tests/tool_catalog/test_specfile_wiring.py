"""Regression guards for the planner <-> spec-file tool wiring.

These lock down the exact breakage found when exposing the CAT-10 chemistry
tools: the planner could not reach the `spec-file` tree that hosts both its
convergence tools and the new interpretation tools, and tools_config.json's
cli_path had drifted from where the CLI actually dispatches the tools.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONFIG_PATH = REPO_ROOT / "beamline_tools" / "tools_config.json"
PLANNER_AGENT = REPO_ROOT / ".claude" / "agents" / "planner.md"

# Tools that live under spec-file at runtime: the convergence/analysis tools
# the planner has always needed, plus the six CAT-10 chemistry tools.
SPEC_FILE_TOOLS = [
    "analyze_efficiency", "analyze_feature_evolution", "analyze_convergence",
    "average_scans", "plot_scan", "list_scans",
    "summarize_sample_chemistry", "extract_xas_descriptors",
    "interpret_oxidation_state", "interpret_coordination_geometry",
    "record_energy_calibration", "get_energy_calibration",
]


def _config_tools() -> dict[str, dict]:
    data = json.loads(CONFIG_PATH.read_text())
    return {t["name"]: t for t in data["tools"]}


def test_planner_agent_can_reach_spec_file_tree():
    """The planner's tool allowlist must include the spec-file tree — the
    convergence AND chemistry tools live there and are otherwise unreachable."""
    text = PLANNER_AGENT.read_text()
    tools_line = next(l for l in text.splitlines() if l.startswith("tools:"))
    assert "beamtimehero spec-file *" in tools_line, (
        "planner.md frontmatter must grant Bash(beamtimehero spec-file *)"
    )


def test_spec_file_tools_categorize_consistently():
    """cli_path in tools_config must match where the CLI actually dispatches
    each tool (the generator delegates to the same categorize() as dispatch)."""
    import beamtimehero_cli.tool_catalog.categorize as cat_mod
    from beamline_tools.tool_catalog.lineage import TOOL_LINEAGE
    from beamline_tools.tool_catalog import TOOL_DEFINITIONS

    cat_mod.TOOL_LINEAGE = TOOL_LINEAGE  # same patch scripts/beamtimehero applies

    # A few names (plot_scan, list_scans) have both a spec-file and an s3df
    # definition; both are valid runtime trees, so collect the set per name.
    trees_by_name: dict[str, set[str]] = {}
    for d in TOOL_DEFINITIONS:
        trees_by_name.setdefault(d["function"]["name"], set()).add(
            "/".join(cat_mod.categorize(d))
        )
    cfg = _config_tools()

    for name in SPEC_FILE_TOOLS:
        assert name in trees_by_name, f"{name} missing from tool definitions"
        assert "spec-file" in trees_by_name[name], (
            f"{name} dispatches under {trees_by_name[name]}, expected spec-file among them"
        )
        # For this local file-cache deployment the config pins the spec-file
        # variant — guards the generator's collision preference and honesty.
        assert cfg[name]["cli_path"] == "spec-file", (
            f"tools_config cli_path for {name} is {cfg[name]['cli_path']!r}, "
            "out of sync with runtime dispatch"
        )
        assert cfg[name]["enabled"] is True, f"{name} must stay enabled"


def test_record_observable_trend_registered_and_dispatchable():
    from beamline_tools.tool_catalog.arg_models import ARG_MODELS
    from beamline_tools.tool_catalog.definitions import TOOL_DESCRIPTIONS
    from beamline_tools.tool_catalog import tools as tools_mod

    assert "record_observable_trend" in ARG_MODELS
    assert "record_observable_trend" in TOOL_DESCRIPTIONS
    assert "record_observable_trend" in tools_mod.DISPATCH

    cfg = _config_tools()
    entry = cfg.get("record_observable_trend")
    assert entry is not None, "record_observable_trend missing from tools_config"
    assert entry["enabled"] is True
    # DB-tool: reachable by the planner via Bash(beamtimehero db *).
    assert entry["cli_path"] == "db"
