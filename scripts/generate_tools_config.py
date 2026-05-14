#!/usr/bin/env python3
"""Generate beamline_tools/tools_config.json from the tool catalog.

Reads TOOL_DEFINITIONS, TOOL_LINEAGE, and REFERENCE_DOCS to build the
JSON config used by the tool-tester UI and the main app's enable/disable
filtering.

Idempotent: re-running merges new tools and removes deleted ones while
preserving user-edited fields (simulated, working_live, comments, sample_output, enabled).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Simulation bootstrap (same as scripts/beamtimehero)
try:
    import simulation
    simulation.bootstrap()
except Exception as e:
    print(f"warning: simulation bootstrap failed: {e}", file=sys.stderr)

try:
    import orchestration  # noqa: F401 — registers CAT-8 tools
except Exception as e:
    print(f"warning: orchestration import failed: {e}", file=sys.stderr)

# Import raw (unfiltered) definitions — the generator must see ALL tools,
# not just those currently enabled in tools_config.json.
from beamline_tools.tool_catalog.autonomy_definitions import (
    AUTONOMY_TOOL_DEFINITIONS as _AUTONOMY_TOOLS,
)
from beamline_tools.tool_catalog.cli import REFERENCE_DOCS
from beamline_tools.tool_catalog.lineage import TOOL_LINEAGE

# Also grab any dynamically registered tools (CAT-8 from orchestration).
from beamline_tools.tool_catalog import TOOL_DEFINITIONS as _FILTERED
_REGISTERED_NAMES = {d["function"]["name"] for d in _FILTERED}
_RAW_NAMES = {d["function"]["name"] for d in _AUTONOMY_TOOLS}
_EXTRA = [d for d in _FILTERED if d["function"]["name"] not in _RAW_NAMES]

TOOL_DEFINITIONS = list(_AUTONOMY_TOOLS) + _EXTRA

CONFIG_PATH = ROOT / "beamline_tools" / "tools_config.json"

# User-edited fields that survive re-generation
_PRESERVE_KEYS = {"enabled", "simulated", "working_live", "comments", "sample_output"}

# Hand-written steering commands (not in TOOL_DEFINITIONS; they manipulate
# StaffGuidance lifecycle columns directly).
_STEERING_COMMANDS = [
    {
        "name": "steering_pending",
        "description": (
            "List pending steering rows (completed_at IS NULL) as a JSON array. "
            "Optionally filter by experiment or show only unacknowledged rows."
        ),
        "when_to_use": "List pending staff-guidance rows to see what needs to be acknowledged or completed.",
        "sample_input": {},
        "positional_args": [],
    },
    {
        "name": "steering_ack",
        "description": (
            "Set active_agent_ack_at on a steering row; optionally link agent_run_id. "
            "Defaults to $BEAMTIMEHERO_AGENT_RUN_ID if not provided."
        ),
        "when_to_use": "Acknowledge a pending steering row so the orchestrator knows the agent has seen it.",
        "sample_input": {"id": "example"},
        "positional_args": ["id"],
    },
    {
        "name": "steering_set_comment",
        "description": "Write or update the ack_comment field on a steering row.",
        "when_to_use": "Add a comment to a steering row to record agent notes or status updates.",
        "sample_input": {"id": "example", "text": "example"},
        "positional_args": ["id", "text"],
    },
    {
        "name": "steering_complete",
        "description": "Mark a steering row complete: write result text and set completed_at timestamp.",
        "when_to_use": "Mark a steering row as done after fulfilling the staff guidance.",
        "sample_input": {"id": "example", "result": "example"},
        "positional_args": ["id"],
    },
    {
        "name": "steering_defer",
        "description": (
            "Defer a steering row by writing 'deferred — <reason>' as ack_comment "
            "without setting completed_at. Optionally specify a target agent type "
            "for orchestrator re-dispatch."
        ),
        "when_to_use": "Defer a steering row when it cannot be handled now and should be re-dispatched later.",
        "sample_input": {"id": "example", "reason": "example"},
        "positional_args": ["id"],
    },
]


def _categorize(tool_def: dict) -> str:
    """Derive CLI tree from tool schema (mirrors scripts/beamtimehero logic)."""
    name = tool_def["function"]["name"]
    lineage = TOOL_LINEAGE.get(name) or {}
    if lineage.get("source") == "autonomy_db":
        return "db"
    params = tool_def["function"].get("parameters", {}) or {}
    required = set(params.get("required", []) or [])
    if "justification" in required:
        return "spec-write"
    spec_cmd = lineage.get("spec_command")
    if spec_cmd is not None:
        return "spec-read"
    return "tool"


def _sample_value(prop: dict) -> object:
    """Generate a placeholder value from a JSON-schema property."""
    if "enum" in prop:
        return prop["enum"][0]
    if "default" in prop:
        return prop["default"]
    t = prop.get("type", "string")
    if t == "integer":
        return 1
    if t == "number":
        return 0.0
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object":
        return {}
    return "example"


def _build_sample_input(tool_def: dict) -> dict:
    """Build sample_input from schema properties (required fields only)."""
    fn = tool_def.get("function", {})
    params = fn.get("parameters", {}) or {}
    properties = params.get("properties", {}) or {}
    required = set(params.get("required", []) or [])
    sample = {}
    for key, prop in properties.items():
        if key == "justification":
            sample[key] = "Testing tool via tool-tester"
            continue
        if key in required:
            sample[key] = _sample_value(prop or {})
    return sample


def _build_tool_entry(tool_def: dict) -> dict:
    """Build a config entry for one tool definition."""
    fn = tool_def.get("function", {})
    name = fn["name"]
    lineage = TOOL_LINEAGE.get(name, {})
    description = lineage.get("long_description", fn.get("description", ""))
    when_to_use = fn.get("description", "")
    return {
        "name": name,
        "cli_path": _categorize(tool_def),
        "description": description,
        "when_to_use": when_to_use,
        "enabled": True,
        "sample_input": _build_sample_input(tool_def),
        "sample_output": "",
        "simulated": False,
        "working_live": False,
        "comments": "",
    }


def _build_ref_entry(ref_name: str, ref_info: dict) -> dict:
    """Build a config entry for a reference document."""
    return {
        "name": ref_name,
        "cli_path": "ref",
        "description": ref_info["description"],
        "when_to_use": f"When operator asks about {ref_info['description'].lower()}",
        "enabled": True,
        "sample_input": {},
        "sample_output": "",
        "simulated": False,
        "working_live": False,
        "comments": "",
    }


def _build_steering_entry(cmd: dict) -> dict:
    """Build a config entry for a hand-written steering subcommand."""
    return {
        "name": cmd["name"],
        "cli_path": "steering",
        "description": cmd["description"],
        "when_to_use": cmd["when_to_use"],
        "enabled": True,
        "sample_input": dict(cmd["sample_input"]),
        "positional_args": list(cmd["positional_args"]),
        "sample_output": "",
        "simulated": False,
        "working_live": False,
        "comments": "",
    }


def generate() -> dict:
    """Generate the full config, merging with existing if present."""
    # Build fresh entries
    fresh: dict[str, dict] = {}
    for tdef in TOOL_DEFINITIONS:
        entry = _build_tool_entry(tdef)
        fresh[entry["name"]] = entry
    for ref_name, ref_info in REFERENCE_DOCS.items():
        entry = _build_ref_entry(ref_name, ref_info)
        fresh[entry["name"]] = entry
    for scmd in _STEERING_COMMANDS:
        entry = _build_steering_entry(scmd)
        fresh[entry["name"]] = entry

    # Load existing config for merge
    existing: dict[str, dict] = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            for tool in data.get("tools", []):
                existing[tool["name"]] = tool
        except Exception as e:
            print(f"warning: could not read existing config: {e}", file=sys.stderr)

    # Merge: preserve user-edited fields from existing
    tools = []
    for name, entry in fresh.items():
        if name in existing:
            for key in _PRESERVE_KEYS:
                if key in existing[name]:
                    entry[key] = existing[name][key]
        tools.append(entry)

    # Sort by cli_path then name for readability
    category_order = {"tool": 0, "db": 1, "spec-read": 2, "spec-write": 3, "steering": 4, "ref": 5}
    tools.sort(key=lambda t: (category_order.get(t["cli_path"], 99), t["name"]))

    config = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_tools": len(tools),
            "generator": "scripts/generate_tools_config.py",
        },
        "tools": tools,
    }
    return config


def main():
    config = generate()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print(f"Wrote {config['_meta']['total_tools']} tools to {CONFIG_PATH}")

    # Summary by category
    from collections import Counter
    cats = Counter(t["cli_path"] for t in config["tools"])
    for cat, count in sorted(cats.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
