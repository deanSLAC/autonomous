"""Schema parity for the generated CAT-8 tool definitions.

`definitions.AUTONOMY_TOOL_DEFINITIONS` is now generated from the
pydantic arg models in `arg_models.py`. The snapshot below was captured
from the last hand-written version of `definitions.py` (pre-swap) and
pins, for every CAT-8 tool: the param names, the required set, each
param's JSON type (absent = intentionally untyped, e.g. the int-or-list
`reps_per_spot`), enum values, and schema defaults.

A second test pins the schema vocabulary to what upstream's
`beamtimehero_cli.cli.__main__.add_arg` understands — type / description
/ default / enum + the required list. No $defs/$ref/anyOf/title/items.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.tool_catalog.arg_models import ARG_MODELS  # noqa: E402
from beamline_tools.tool_catalog.definitions import (  # noqa: E402
    AUTONOMY_TOOL_DEFINITIONS,
    TOOL_DESCRIPTIONS,
)

# Canonical CAT-8 tool order (hand-written definitions.py, pre-swap).
EXPECTED_ORDER = [
    "request_human_intervention",
    "post_status_update",
    "log_status_assessment",
    "update_plan",
    "record_sample_progress",
    "record_convergence_stats",
    "get_plan",
    "get_experiment_config",
    "get_remaining_beamtime",
    "set_experiment_end_time",
    "get_staff_guidance",
    "list_open_interventions",
    "set_sample_time_budget",
    "set_holder_time_budget",
    "get_holder_time_budget",
    "get_scans_since_last_plan_update",
    "get_scans_for_active_sample",
    "upload_sample_alignment_results",
    "upload_sample_survey_results",
    "get_comprehensive_collection_plan",
    "record_completed_scan",
    "regenerate_plan",
]

# {tool: {"params": {name: {type?, enum?, default?}}, "required": sorted [...]}}
SNAPSHOT = {
    "request_human_intervention": {
        "params": {
            "kind": {"type": "string",
                     "enum": ["crystal_install", "sample_mount", "foil_insert",
                              "hardware_reset", "custom"]},
            "detail": {"type": "string"},
        },
        "required": ["detail", "kind"],
    },
    "post_status_update": {
        "params": {"text": {"type": "string"}},
        "required": ["text"],
    },
    "log_status_assessment": {
        "params": {"text": {"type": "string"}},
        "required": ["text"],
    },
    "update_plan": {
        "params": {"plan": {"type": "object"}},
        "required": ["plan"],
    },
    "record_sample_progress": {
        "params": {
            "sample_id": {"type": "string"},
            "status": {"type": "string",
                       "enum": ["queued", "in_progress", "done",
                                "skipped", "failed"]},
            "snr_estimate": {"type": "number"},
            "efficiency_verdict": {"type": "string",
                                   "enum": ["needs_more", "reasonable",
                                            "marginal", "wasteful"]},
            "reps_completed": {"type": "integer"},
            "note": {"type": "string"},
        },
        "required": ["sample_id"],
    },
    "record_convergence_stats": {
        "params": {
            "sample_id": {"type": "string"},
            "stats": {"type": "object"},
        },
        "required": ["sample_id", "stats"],
    },
    "get_plan": {"params": {}, "required": []},
    "get_experiment_config": {"params": {}, "required": []},
    "get_remaining_beamtime": {"params": {}, "required": []},
    "set_experiment_end_time": {
        "params": {
            "end_time": {"type": "string"},
            "hours_from_now": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": [],
    },
    "get_staff_guidance": {
        "params": {"limit": {"type": "integer"}},
        "required": [],
    },
    "list_open_interventions": {"params": {}, "required": []},
    "set_sample_time_budget": {
        "params": {
            "sample_id": {"type": "string"},
            "count_time_s": {"type": "number"},
            "reps": {"type": "integer"},
            "reps_per_spot": {},  # intentionally untyped: int OR list[int]
            "n_spots": {"type": "integer"},
            "mode": {"type": "string", "enum": ["xas", "emiss"]},
            "reason": {"type": "string"},
        },
        "required": ["sample_id"],
    },
    "set_holder_time_budget": {
        "params": {
            "holder_id": {"type": "string"},
            "count_time_s": {"type": "number"},
            "reps": {"type": "integer"},
            "mode": {"type": "string", "enum": ["xas", "emiss"]},
            "apply_to_existing": {"type": "boolean", "default": True},
            "stop_time": {"type": "string"},
            "hours_remaining": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": [],
    },
    "get_holder_time_budget": {
        "params": {"holder_id": {"type": "string"}},
        "required": [],
    },
    "get_scans_since_last_plan_update": {
        "params": {"experiment_id": {"type": "string"}},
        "required": [],
    },
    "get_scans_for_active_sample": {
        "params": {"sample_id": {"type": "string"}},
        "required": [],
    },
    "upload_sample_alignment_results": {
        "params": {
            "justification": {"type": "string"},
            "results": {"type": "array"},
        },
        "required": ["justification", "results"],
    },
    "upload_sample_survey_results": {
        "params": {
            "justification": {"type": "string"},
            "results": {"type": "array"},
        },
        "required": ["justification", "results"],
    },
    "get_comprehensive_collection_plan": {
        "params": {"sample_holder_id": {"type": "string"}},
        "required": [],
    },
    "record_completed_scan": {
        "params": {
            "justification": {"type": "string"},
            "sample_id": {"type": "string"},
            "scan_number": {"type": "integer"},
            "technique": {"type": "string",
                          "enum": ["xas", "herfd", "rixs", "vtc"],
                          "default": "xas"},
            "filter_setting": {"type": "integer"},
            "count_time": {"type": "number"},
            "spec_datafile": {"type": "string"},
            "spot_index": {"type": "integer"},
        },
        "required": ["justification"],
    },
    "regenerate_plan": {
        "params": {
            "beamtime_hours": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": [],
    },
}


def _by_name() -> dict[str, dict]:
    return {d["function"]["name"]: d["function"] for d in AUTONOMY_TOOL_DEFINITIONS}


def test_tool_names_and_order_match_snapshot():
    names = [d["function"]["name"] for d in AUTONOMY_TOOL_DEFINITIONS]
    assert names == EXPECTED_ORDER
    assert set(SNAPSHOT) == set(names)
    assert set(ARG_MODELS) == set(names)
    assert set(TOOL_DESCRIPTIONS) == set(names)


def test_generated_schemas_match_handwritten_snapshot():
    fns = _by_name()
    for tool, expected in SNAPSHOT.items():
        params = fns[tool]["parameters"]
        props = params.get("properties") or {}
        # param names
        assert set(props) == set(expected["params"]), tool
        # required set
        assert sorted(params.get("required") or []) == expected["required"], tool
        # per-param type / enum / default
        for pname, exp in expected["params"].items():
            got = props[pname]
            assert got.get("type") == exp.get("type"), f"{tool}.{pname} type"
            assert got.get("enum") == exp.get("enum"), f"{tool}.{pname} enum"
            assert got.get("default") == exp.get("default"), f"{tool}.{pname} default"


def test_schemas_stay_within_cli_add_arg_vocabulary():
    """add_arg understands only type/description/default/enum per property
    (plus the required list). Anything else would be silently ignored at
    best — fail loudly here instead."""
    allowed_prop_keys = {"type", "description", "default", "enum"}
    allowed_types = {"string", "integer", "number", "boolean", "array", "object"}
    for d in AUTONOMY_TOOL_DEFINITIONS:
        fn = d["function"]
        params = fn["parameters"]
        assert set(params) == {"type", "properties", "required"}, fn["name"]
        assert params["type"] == "object"
        for pname, prop in params["properties"].items():
            extra = set(prop) - allowed_prop_keys
            assert not extra, f"{fn['name']}.{pname} has keys {extra}"
            if "type" in prop:
                assert prop["type"] in allowed_types, f"{fn['name']}.{pname}"


def test_every_tool_has_nonempty_description():
    for d in AUTONOMY_TOOL_DEFINITIONS:
        assert (d["function"].get("description") or "").strip(), d["function"]["name"]
