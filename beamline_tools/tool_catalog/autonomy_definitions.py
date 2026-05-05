"""Tool schemas for the autonomy CAT-0..CAT-8 surface.

Kept in its own module so tools/definitions.py stays readable. The
app-level `TOOL_DEFINITIONS` import concatenates the two lists.
"""

# ---- Shared schema fragments -----------------------------------------------

_J = {
    "justification": {
        "type": "string",
        "description": (
            "REQUIRED for any SPEC-mutating action. Explain in one sentence "
            "why you are taking this action right now (will be stored in "
            "action_log). Empty / missing justifications are rejected."
        ),
    },
}

AUTONOMY_TOOL_DEFINITIONS = [
    # -----------------------------------------------------------------
    # CAT-0 · High-level procedural macros
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "align_beamline",
            "description": (
                "Run the full `align_the_beamline` macro. Multi-minute, optimizes "
                "M1/M2, peaks mono pitch, aligns mono slits, optimizes B stage, "
                "zeros pinhole, measures beam size. Only in phase beamline_alignment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "energy": {"type": "number", "description": "Target eV (0 = use current)"},
                    "xtal_chg": {"type": "integer", "enum": [0, 1],
                                 "description": "1 if a crystal change just happened (resets anchor)"},
                    "fine_x": {"type": "integer", "enum": [0, 1]},
                    "fine_z": {"type": "integer", "enum": [0, 1]},
                },
                "required": ["justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "align_xes_spectrometer",
            "description": (
                "Run `run_spec_align` to align the 7-crystal HERFD analyzer. "
                "Only in phase xes_alignment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "crystals": {"type": "string",
                                 "description": "Subset of '1234567' (e.g. '1234' aligns crystals 1-4)"},
                    "en_xes": {"type": "number", "description": "XES emission energy (0 = current)"},
                    "en_mono": {"type": "number", "description": "Mono energy (0 = current)"},
                },
                "required": ["justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sample_alignment",
            "description": "Run `auto_sample_align`. Only in phase sample_alignment.",
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_collection",
            "description": (
                "Run `run_collection` — the multi-sample data collection loop "
                "that cycles through every enabled sample. Only in phase collection."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_element",
            "description": (
                "Switch the beamline to the experiment's configured geometry for "
                "a single element (energy, emiss, Vortex ROI, xes_setup)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "element": {"type": "string", "description": "E.g. 'Fe', 'Cu'"},
                },
                "required": ["justification", "element"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "peak_mono_pitch",
            "description": "LVDT-driven piezo optimization of the 2nd mono crystal pitch.",
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calibrate_mono_from_foil_scan",
            "description": (
                "Standard calibration: dscan energy ±15 eV around a reference foil, "
                "find the inflection, and call calibrate_mono + reset_gap. "
                "`tabulated_edge_ev` must be within 5 eV of current energy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "tabulated_edge_ev": {"type": "number"},
                },
                "required": ["justification", "tabulated_edge_ev"],
            },
        },
    },

    # -----------------------------------------------------------------
    # CAT-1 · Motor control
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "move_motor",
            "description": "Absolute motor move (umv). Motor must be on the current phase's allowlist.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "motor": {"type": "string"},
                    "position": {"type": "number"},
                },
                "required": ["justification", "motor", "position"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_motor_relative",
            "description": "Relative motor move (umvr).",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "motor": {"type": "string"},
                    "delta": {"type": "number"},
                },
                "required": ["justification", "motor", "delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_motor_position",
            "description": "Read a single motor's current position (parsed float).",
            "parameters": {
                "type": "object",
                "properties": {"motor": {"type": "string"}},
                "required": ["motor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_all_positions",
            "description": "Read all motor positions (wa) with parsed name→value map.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },

    # -----------------------------------------------------------------
    # CAT-2 · Scans
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "run_motor_scan",
            "description": "ascan — absolute motor scan.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "motor": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "npoints": {"type": "integer"},
                    "count_time": {"type": "number"},
                },
                "required": ["justification", "motor", "start", "end", "npoints", "count_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_motor_scan_relative",
            "description": "dscan — delta scan around the current position.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "motor": {"type": "string"},
                    "delta_start": {"type": "number"},
                    "delta_end": {"type": "number"},
                    "npoints": {"type": "integer"},
                    "count_time": {"type": "number"},
                },
                "required": [
                    "justification", "motor",
                    "delta_start", "delta_end", "npoints", "count_time",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_xas",
            "description": (
                "Element-specific XAS (<element>_xas). Beam must be present; count_time ≤ 60 s; reps ≤ 20."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "element": {"type": "string"},
                    "count_time": {"type": "number"},
                    "n_reps": {"type": "integer"},
                    "emission_ev": {"type": "number"},
                },
                "required": ["justification", "element", "count_time", "n_reps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_emiss_scan",
            "description": "Element-specific emission-energy (_cee) scan.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "element": {"type": "string"},
                    "count_time": {"type": "number"},
                    "n_reps": {"type": "integer"},
                    "emission_ev": {"type": "number"},
                    "filter": {"type": "integer", "description": "0-255 bitmask"},
                },
                "required": [
                    "justification", "element",
                    "count_time", "n_reps", "emission_ev",
                ],
            },
        },
    },

    # -----------------------------------------------------------------
    # CAT-3 · Beamline configuration
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "mv_energy",
            "description": "Move incident energy (tracking on; moves mono + gap).",
            "parameters": {
                "type": "object",
                "properties": {**_J, "energy_ev": {"type": "number"}},
                "required": ["justification", "energy_ev"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shutter",
            "description": "Fast-shutter control.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "command": {"type": "string", "enum": ["fsopen", "fsclose", "fson", "fsoff"]},
                    "delay_s": {"type": "number"},
                },
                "required": ["justification", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_filter",
            "description": "Set the filter motor (0-255 bitmask).",
            "parameters": {
                "type": "object",
                "properties": {**_J, "bitmask": {"type": "integer"}},
                "required": ["justification", "bitmask"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "safely_remove_filters",
            "description": "Remove filters using the XRS-safe macro.",
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_gain",
            "description": "Set I0/I1/I2 SRS gain (string, e.g. '50 nA/V').",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "which": {"type": "string", "enum": ["i0", "i1", "i2"]},
                    "gain_setting": {"type": "string"},
                },
                "required": ["justification", "which", "gain_setting"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_vortex_roi",
            "description": "Set Vortex ROI. mode='auto': bounds ±200 eV around the emission line for channel (1=vortDT, 3=vortDT2). mode='explicit': set channel + lo_ev/hi_ev in eV directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "mode": {"type": "string", "enum": ["auto", "explicit"]},
                    "channel": {"type": "integer"},
                    "lo_ev": {"type": "number"},
                    "hi_ev": {"type": "number"},
                },
                "required": ["justification", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_data_file",
            "description": "newfile — start a new SPEC data file (per-sample).",
            "parameters": {
                "type": "object",
                "properties": {**_J, "filename": {"type": "string"}},
                "required": ["justification", "filename"],
            },
        },
    },

    # -----------------------------------------------------------------
    # CAT-4 · Alignment fallbacks
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "run_align_shortcut",
            "description": (
                "Run one of the named diagnostic shortcuts (vvv/hhh/m1m1/m2m2/ggg/bzbz/"
                "bxbx/dmm/beamx/beamz/cm1m1/cm2m2). Each is a single dscan+analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {**_J, "name": {"type": "string"}},
                "required": ["justification", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_scan_move",
            "description": "Post-scan move: 'cen' (feature center) or 'peak' (feature peak).",
            "parameters": {
                "type": "object",
                "properties": {**_J, "mode": {"type": "string", "enum": ["cen", "peak"]}},
                "required": ["justification", "mode"],
            },
        },
    },

    # -----------------------------------------------------------------
    # CAT-6 · Beam monitoring
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_beam_status",
            "description": "SPEAR current + BL15 state + gap ownership + beam_good flag.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_counts",
            "description": "Count for <count_time> seconds and return all counter values (I0, I1, vortDT, etc.).",
            "parameters": {
                "type": "object",
                "properties": {"count_time": {"type": "number"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_counter",
            "description": "Count for <count_time> seconds and return one specific counter's value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "counter": {"type": "string"},
                    "count_time": {"type": "number"},
                },
                "required": ["counter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_gap_ownership",
            "description": "Blocking `gaprequest` — returns when SPEAR grants ownership or times out.",
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },

    # -----------------------------------------------------------------
    # CAT-7 · Run state
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_scan_number",
            "description": "Current SPEC_N and datafile.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_datafile",
            "description": "Returns the active SPEC data file path (DATAFILE global).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "abort_current_scan",
            "description": "Send Ctrl-C to SPEC. Only after confirming a problem.",
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },

    # -----------------------------------------------------------------
    # CAT-8 · Orchestration
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "transition_phase",
            "description": (
                "Advance (or request to revert) the experiment phase. Preconditions "
                "gate forward moves; backward moves go through Slack approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "target_phase": {
                        "type": "string",
                        "enum": [
                            "setup", "beamline_alignment", "xes_alignment",
                            "sample_alignment", "collection", "complete",
                        ],
                    },
                },
                "required": ["justification", "target_phase"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_intervention",
            "description": (
                "Pause the agent and ask a human to complete a physical action "
                "(crystal install, sample mount, foil insert, etc.). Posts to Slack "
                "and blocks until resolved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "crystal_install", "sample_mount", "foil_insert",
                            "hardware_reset", "custom",
                        ],
                    },
                    "detail": {"type": "string", "description": "What you want the human to do."},
                },
                "required": ["kind", "detail"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_status_update",
            "description": "Post a high-level progress message to Slack + UI.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_experiment_plan",
            "description": "Replace the live experiment plan JSON (structure decided by the agent).",
            "parameters": {
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_sample_progress",
            "description": "Update per-sample status (snr_estimate, efficiency_verdict, reps_completed, note).",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["queued", "in_progress", "done", "skipped", "failed"]},
                    "snr_estimate": {"type": "number"},
                    "efficiency_verdict": {"type": "string",
                                           "enum": ["needs_more", "reasonable", "marginal", "wasteful"]},
                    "reps_completed": {"type": "integer"},
                    "note": {"type": "string"},
                },
                "required": ["sample_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_plan",
            "description": "Return the live experiment plan (config + sample queue + budget).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_remaining_beamtime",
            "description": "Total / elapsed / remaining beamtime in hours.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_staff_guidance",
            "description": "Recent staff / user guidance messages (Slack or web).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_open_interventions",
            "description": "List pause-for-human requests still waiting.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_actions",
            "description": "Most recent action_log entries for the current experiment.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_sample_time_budget",
            "description": (
                "Adjust the time budget for a single sample — change either the "
                "per-repetition count time or the number of reps (or both). "
                "Optionally restrict to one mode ('xas' or 'emiss')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "count_time_s": {"type": "number",
                                     "description": "Per-point count time in seconds."},
                    "reps": {"type": "integer",
                             "description": "Number of repetitions."},
                    "mode": {"type": "string", "enum": ["xas", "emiss"],
                             "description": "Restrict the change to this mode (optional)."},
                    "reason": {"type": "string",
                               "description": "Short rationale; written to the plan edit log."},
                },
                "required": ["sample_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_holder_time_budget",
            "description": (
                "Set a default per-sample time budget for an entire sample holder. "
                "Stored under the plan's holder_budgets so new samples inherit it; "
                "when apply_to_existing=true (default), existing samples on that "
                "holder also get the new count_time/reps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_id": {"type": "string",
                                  "description": "Leave blank to apply to every holder."},
                    "count_time_s": {"type": "number"},
                    "reps": {"type": "integer"},
                    "mode": {"type": "string", "enum": ["xas", "emiss"]},
                    "apply_to_existing": {"type": "boolean", "default": True},
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_beamtime_budget",
            "description": "Set the total beamtime budget (in hours) to an absolute value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours_total": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["hours_total"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extend_beamtime_budget",
            "description": "Add (or subtract, with a negative delta) hours to the beamtime budget.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours_delta": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["hours_delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regenerate_plan",
            "description": (
                "Rebuild the sample plan from the database while preserving per-sample "
                "progress (status, reps_completed, notes) and user overrides "
                "(thresholds, holder_budgets, budget). Call this after a new sample "
                "holder is configured or an existing one is edited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "beamtime_hours": {"type": "number",
                                       "description": "Optional new total (default: keep current)."},
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
]

# Category map for the sidebar
AUTONOMY_TOOL_CATEGORIES = [
    ("CAT-0 Procedures", [
        "align_beamline", "align_xes_spectrometer", "run_sample_alignment",
        "run_collection", "select_element", "peak_mono_pitch",
        "calibrate_mono_from_foil_scan",
    ]),
    ("CAT-1 Motors", [
        "move_motor", "move_motor_relative", "read_motor_position",
        "read_all_positions",
    ]),
    ("CAT-2 Scans", [
        "run_motor_scan", "run_motor_scan_relative", "run_xas", "run_emiss_scan",
    ]),
    ("CAT-3 Config", [
        "mv_energy", "shutter", "set_filter", "safely_remove_filters",
        "set_gain", "set_vortex_roi", "open_data_file",
    ]),
    ("CAT-4 Align Fallbacks", ["run_align_shortcut", "post_scan_move"]),
    ("CAT-6 Beam", ["get_beam_status", "get_counts", "get_counter", "request_gap_ownership"]),
    ("CAT-7 State", ["get_scan_number", "get_current_datafile", "abort_current_scan"]),
    ("CAT-8 Orchestration", [
        "transition_phase", "request_human_intervention", "post_status_update",
        "update_experiment_plan", "record_sample_progress", "get_experiment_plan",
        "get_remaining_beamtime", "get_staff_guidance", "list_open_interventions",
        "recent_actions",
        "set_sample_time_budget", "set_holder_time_budget",
        "set_beamtime_budget", "extend_beamtime_budget", "regenerate_plan",
    ]),
]
