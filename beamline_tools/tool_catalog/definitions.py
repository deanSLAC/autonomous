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
            "name": "calibrate_mono",
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
            "name": "run_diagonal_scan",
            "description": (
                "d2scan — relative scan of two motors moving in lockstep, "
                "each spanning the same delta range over the same number "
                "of points. Common use: map a sample's footprint in the "
                "Sx/Sy plane to find its edges (the staple of "
                "auto_sample_align's per-sample boundary detection). "
                "Default range is ±8. NOTE: the `cen` scan-followup "
                "command does not work properly on a d2scan (2D scan) — "
                "do not rely on `post_scan_move` with mode='cen' after "
                "this scan; compute the center yourself and move "
                "explicitly instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "motor1": {"type": "string",
                               "description": "First motor (e.g. 'Sx')."},
                    "motor2": {"type": "string",
                               "description": "Second motor (e.g. 'Sy')."},
                    "npoints": {"type": "integer"},
                    "count_time": {"type": "number",
                                   "description": "Seconds per point."},
                    "delta": {
                        "type": "number",
                        "description": (
                            "Symmetric shorthand for `delta_lo=-delta, "
                            "delta_hi=+delta`. Mutually exclusive with "
                            "`delta_lo`/`delta_hi` — pass either `delta` "
                            "alone, or `delta_lo`+`delta_hi`, not both."
                        ),
                    },
                    "delta_lo": {
                        "type": "number", "default": -8,
                        "description": "Lower delta bound. Applied to both motors. Default -8.",
                    },
                    "delta_hi": {
                        "type": "number", "default": 8,
                        "description": "Upper delta bound. Applied to both motors. Default 8.",
                    },
                },
                "required": ["justification", "motor1", "motor2",
                             "npoints", "count_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fit_emission_peak",
            "description": (
                "Fit the most recent (or specified) emission scan with the "
                "lab's Pseudo-Voigt+skew model and return the suggested "
                "emission energy in eV. Does NOT move the spectrometer — "
                "the agent decides whether/how to apply the value. Wraps "
                "the SPEC `get_HERFD_energy` macro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "scan_number": {
                        "type": "integer",
                        "description": (
                            "Scan number to fit. If omitted, the most "
                            "recent scan in the active datafile is used."
                        ),
                    },
                },
                "required": ["justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_xas",
            "description": (
                "This command will call the _xas macro function for spectrum "
                "collection based on the element set by select_element. All "
                "args get passed onto the <El>_xas func: \"<El>_xas  cntSec  "
                "nbrScan  emission  nbrFilter\". Null value for cntSec "
                "defaults to 1s, nbrScan to 1, if emission is zero the emiss "
                "is not moved, if nbrFilter <0 then filter motor isnt moved. "
                "Optional `element` arg first runs select_element(<element>) "
                "for the convenience of single-call element switching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "element": {
                        "type": "string",
                        "description": (
                            "Optional. If provided, runs select_element(<element>) "
                            "before the XAS scan (sets energy, emiss, ROI, "
                            "plot-selected counter). E.g. 'Fe', 'Cu', 'Au'. "
                            "Omit if the element is already set."
                        ),
                    },
                    "count_time": {
                        "type": "number",
                        "description": "cntSec — null defaults to 1 s.",
                    },
                    "n_reps": {
                        "type": "integer",
                        "description": "nbrScan — null defaults to 1.",
                    },
                    "emission_ev": {
                        "type": "number",
                        "description": "emission — 0 leaves emiss motor unchanged.",
                    },
                    "filter": {
                        "type": "integer",
                        "description": "nbrFilter — value <0 leaves filter motor unchanged.",
                    },
                },
                "required": ["justification"],
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

    {
        "type": "function",
        "function": {
            "name": "plotselect",
            "description": (
                "Select which counter SPEC plots during subsequent scans. "
                "Use I1 for alignment optimization, vortDT for fluorescence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "counter": {
                        "type": "string",
                        "description": "Counter name (e.g. 'I0', 'I1', 'vortDT')",
                    },
                },
                "required": ["justification", "counter"],
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
    # CAT-5 · Beam-diagnostic tool (sample-position diagnostic, alignment)
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "mv_pinhole",
            "description": (
                "Move the sample stage so the diagnostic-tool pinhole is in the beam. "
                "Used to set the sample reference position. Sx/Sy/Sz/Sr are driven to "
                "the pinhole pose (plus any active pinhole_offset)."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mv_plastic",
            "description": (
                "Move the sample stage so the diagnostic-tool plastic scatterer is in the beam. "
                "Used to generate elastic scatter for XES spectrometer alignment."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mv_knife_clear",
            "description": (
                "Move the sample stage so the knife-edge blades are clear of the beam. "
                "Fast move, but the diagnostic body may still partially clip the beam to I1. "
                "Use mv_knife_out instead before trusting I1 for upstream-optic alignment."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mv_knife_out",
            "description": (
                "Move the sample stage so the entire diagnostic tool is fully out of the beam. "
                "Slower than mv_knife_clear (large Sr rotation), but unambiguous: nothing "
                "diagnostic-related is in the beam path. Use this before optimizing upstream "
                "optics with I1."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "measure_beam_size",
            "description": (
                "Knife-edge scan to measure horizontal and vertical beam FWHM. Multi-minute. "
                "Removes filters and ensures DATAFILE=alignment. Each axis can be measured "
                "in 'big' (false, ~mm-scale beam) or 'small' (true, ~50um focused) mode; "
                "wrong mode produces artifacts. Standard configuration is small_x=false, "
                "small_z=false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "small_x": {
                        "type": "boolean",
                        "description": "True for tightly-focused horizontal beam (~50um); false (default) for big-beam benders.",
                        "default": False,
                    },
                    "small_z": {
                        "type": "boolean",
                        "description": "True for tightly-focused vertical beam (~50um); false (default) for big-beam benders.",
                        "default": False,
                    },
                },
                "required": ["justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "zero_pinhole",
            "description": (
                "Center the beam on the diagnostic-tool pinhole, then zero (or apply the "
                "configured pinhole_offset to) Tz/Sz/Bz/Tx/Sx/Bx. Multi-minute. Refuses to "
                "run if the table is not in its usual position (Tz < 15.5 with no offset "
                "configured)."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "small_beam",
            "description": (
                "Set the KB-mirror benders to the small-beam preset (~50um focused). Moves "
                "m1ubend/m1dbend/m2ubend/m2dbend to the configured small-beam positions and "
                "tags both beamsize_mode axes as 'small'. After running, alignment routines "
                "and measure_beam_size should be invoked in their small-beam mode."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "big_beam",
            "description": (
                "Set the KB-mirror benders to the big-beam preset (mm-scale, standard "
                "configuration). Moves m1ubend/m1dbend/m2ubend/m2dbend to the configured "
                "big-beam positions and tags both beamsize_mode axes as 'big'."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "xtal_align",
            "description": (
                "Recalibrate the crystal motor encoder zero. Runs a dscan over the "
                "crystal motor, peaks on the diffraction feature, then redefines the "
                "current encoder reading to the original (pre-scan) value -- so the "
                "motor effectively stays in place but its zero is now on the peak. Use "
                "after a crystal swap or when the crystal feature has drifted."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reset_gap",
            "description": (
                "Recalibrate the undulator gap encoder. Runs ggg (gap dscan), peaks on "
                "the flux maximum, then redefines the gap encoder so the original "
                "(pre-scan) reading is preserved on the new peak. Run ONCE at the end of "
                "an energy-calibration sequence -- iterating reset_gap during calibration "
                "fights the calibrate_mono loop."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_m2_stripe",
            "description": (
                "Move M2 (m2vert) to the correct stripe for a given incident energy. "
                "Below 4500 eV the macro defaults to the Rh stripe with a warning; "
                "between 4500 and 6200 eV it selects the Si stripe (m2vert=9.69); at "
                "or above 6200 eV it selects the Rh stripe (m2vert=-3.5). Use after "
                "moving incident energy across a stripe boundary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "energy_ev": {
                        "type": "number",
                        "description": "Incident energy in eV used to pick the stripe.",
                    },
                },
                "required": ["justification", "energy_ev"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_anchor",
            "description": (
                "Read the current tracking anchor from the SPEC session: "
                "stored energy, m1vert/Tz (and their 1/2 constituents), "
                "crystal id, and SPEAR steering offset captured at "
                "anchor time. Also reports whether SPEAR has visibly "
                "drifted since the anchor was set, or whether the "
                "crystal set has changed (which would invalidate the "
                "anchor for the current geometry)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_anchor",
            "description": (
                "Capture the current positions of mono (energy), m1vert/m1vert1/m1vert2, "
                "and Tz/Tz1/Tz2 (plus monvtra for SPEAR steering) as the tracking-anchor "
                "reference. Subsequent energy moves with tracking enabled use this anchor "
                "as the fixed beam-position pivot. Also writes the anchor to "
                "/usr/local/lib/spec.d/anchor.cfg and a timestamped backup. Call this "
                "once the beam is aligned at a known reference energy."
            ),
            "parameters": {"type": "object", "properties": _J, "required": ["justification"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tracking",
            "description": (
                "Enable or disable energy tracking. When enabled, every energy move also "
                "drives m1vert and Tz so the focused beam stays at the anchor position as "
                "the mono Bragg angle changes. Requires set_anchor to have been called "
                "first -- without an anchor, tracking has no reference and the beam will "
                "drift. Disable before procedures that should leave m1vert/Tz untouched "
                "(e.g. independent KB-mirror alignment)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable tracking, false to disable.",
                    },
                },
                "required": ["justification", "enabled"],
            },
        },
    },

    # -----------------------------------------------------------------
    # CAT-6 · Beam monitoring
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_beam_size",
            "description": (
                "Return the last-measured horizontal and vertical beam FWHM (mm) "
                "and the current beam-size mode (big/small/unknown) for each axis."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
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
            "name": "get_element",
            "description": (
                "Return the currently active element and all configured elements "
                "with their incident and emission energies."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
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
            "name": "get_plotselected_counter",
            "description": (
                "Return the currently plot-selected counter mnemonic — "
                "the counter peak/cen will operate on after a scan, set "
                "by the most recent plotselect. Resolves SPEC's DET "
                "global via cnt_mne(DET). Use after select_element or "
                "plotselect to confirm SPEC matches the expected counter."
            ),
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
            "name": "log_status_assessment",
            "description": (
                "Append the planner's STATUS ASSESSMENT block to "
                "logs/status_assessments_<experiment_id>.jsonl. File-only "
                "record (does not post to Slack)."
            ),
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
            "name": "update_plan",
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
            "name": "record_convergence_stats",
            "description": (
                "Store per-sample convergence statistics from the latest "
                "analysis run. The orchestrator reads these to auto-generate "
                "a statistics trend plot on the dashboard."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "stats": {
                        "type": "object",
                        "description": (
                            "Convergence statistics dict with keys: "
                            "feature_window_eV ([e_min, e_max]), statistic, "
                            "cumulative_cv_pct (array from analyze-efficiency), "
                            "running_sem_frac (array from analyze-feature-evolution), "
                            "efficiency_verdict, feature_verdict."
                        ),
                    },
                },
                "required": ["sample_id", "stats"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plan",
            "description": "Return the live experiment plan (config + sample queue + budget).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_config",
            "description": (
                "Return the operator-entered experiment configuration "
                "straight from the DB: experiment-level settings (mono "
                "crystal, beam size, mirrors, sample env, data path), "
                "the configured elements (edges, energies, crystal/HKL, "
                "vortex counter mnemonic — vortDT/vortDT2/vortDT3/vortDT4), "
                "and every sample holder with its "
                "samples (positions, gains, XAS/RIXS plan). Use this "
                "when you need ground truth from the /config form, "
                "independent of the live plan JSON."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_remaining_beamtime",
            "description": (
                "Hours from now until Experiment.end_time. Returns "
                "{remaining_hours, end_time} — or both null with a "
                "note if the operator has not yet called "
                "set_experiment_end_time."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_experiment_end_time",
            "description": (
                "Set the absolute end-of-beamtime timestamp on the "
                "active experiment. Accepts ISO-8601 `end_time` OR "
                "`hours_from_now` (one or the other, not both)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "end_time": {
                        "type": "string",
                        "description": "ISO-8601 timestamp (e.g. '2026-05-10T18:00:00').",
                    },
                    "hours_from_now": {
                        "type": "number",
                        "description": "Hours from current time.",
                    },
                    "reason": {"type": "string"},
                },
                "required": [],
            },
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
                "Adjust the time budget for a single sample. Tweak any "
                "of: per-rep count_time_s, total reps, reps_per_spot "
                "(int = even split, list[int] = explicit per-spot), "
                "n_spots. Optionally restrict to one mode ('xas' or "
                "'emiss')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "count_time_s": {"type": "number",
                                     "description": "Per-point count time in seconds."},
                    "reps": {"type": "integer",
                             "description": "Total number of repetitions across all spots."},
                    "reps_per_spot": {
                        "description": (
                            "Either an integer (even split: every spot gets this many) "
                            "or a list of integers (explicit per-spot reps; length "
                            "implies n_spots and total reps = sum)."
                        ),
                    },
                    "n_spots": {"type": "integer",
                                "description": "Number of spots to visit on this sample."},
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
                "holder also get the new count_time/reps. Can also set a stop_time "
                "(absolute deadline) or hours_remaining (relative deadline) on the "
                "holder row — the holder's collection should finish by that time."
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
                    "stop_time": {
                        "type": "string",
                        "description": "ISO-8601 absolute deadline (e.g. '2026-05-10T18:00:00').",
                    },
                    "hours_remaining": {
                        "type": "number",
                        "description": "Hours from now until the holder deadline. Mutually exclusive with stop_time.",
                    },
                    "reason": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_holder_time_budget",
            "description": (
                "Return the time budget for one or all holders: beamtime_hours, "
                "stop_time (absolute deadline), and hours_remaining (computed). "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_id": {
                        "type": "string",
                        "description": "Optional; omit to return all holders.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scans_since_last_plan_update",
            "description": (
                "Return every CollectionScan row whose timestamp is "
                "newer than the live ExperimentPlan.updated_at. Used by "
                "the Planner to see what data has been collected since "
                "it last revised the plan. Sample names are joined in "
                "from SamplePosition. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string",
                                      "description": "Optional override; defaults to active experiment."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scans_for_active_sample",
            "description": (
                "Return every CollectionScan for the currently-active "
                "sample. The active sample is the lowest-queue-order "
                "entry in plan_json's sample_queue whose status is not "
                "'done' (or the explicit `active_sample_id` plan flag, "
                "if set). Pass `sample_id` to override the auto-detect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string",
                                  "description": "Override auto-detected active sample."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_sample_alignment_results",
            "description": (
                "Persist Sample-Alignment agent results to SamplePosition. "
                "Stores per-sample stage boundaries (sx/sy/sz lo/hi), "
                "measured emission energy, suggested starting filter, and "
                "count rate. Called once per sample after the alignment "
                "recipe completes. Justification is required (write op)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "results": {
                        "type": "array",
                        "description": "One entry per aligned sample.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sample_id": {"type": "string"},
                                "sx_lo": {"type": "number", "description": "Sx lower bound"},
                                "sx_hi": {"type": "number", "description": "Sx upper bound"},
                                "sy_lo": {"type": "number", "description": "Sy lower bound"},
                                "sy_hi": {"type": "number", "description": "Sy upper bound"},
                                "sz_lo": {"type": "number", "description": "Sz lower bound"},
                                "sz_hi": {"type": "number", "description": "Sz upper bound"},
                                "emiss_energy_eV": {"type": "number",
                                                    "description": "Measured optimal emission energy (eV)."},
                                "suggested_filter": {"type": "integer", "minimum": 0,
                                                     "description": "Starting filter count for this sample."},
                                "counts_per_sec": {"type": "number", "minimum": 0,
                                                   "description": "Measured count rate at alignment energy."},
                            },
                            "required": ["sample_id", "sx_lo", "sx_hi",
                                         "sy_lo", "sy_hi", "sz_lo", "sz_hi"],
                        },
                    },
                },
                "required": ["justification", "results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_sample_survey_results",
            "description": (
                "Persist Sample-Surveyor results to SamplePosition. "
                "For each entry, overwrites xas_filter with the "
                "filter_count and stores counts_per_sec, survey energy, "
                "and notes. Justification is required (this is a write)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "results": {
                        "type": "array",
                        "description": "One entry per surveyed sample.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sample_id": {"type": "string"},
                                "filter_count": {"type": "integer", "minimum": 0},
                                "counts_per_sec": {"type": "number", "minimum": 0},
                                "survey_energy_ev": {"type": "number"},
                                "notes": {"type": "string"},
                            },
                            "required": ["sample_id", "filter_count", "counts_per_sec"],
                        },
                    },
                },
                "required": ["justification", "results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_comprehensive_collection_plan",
            "description": (
                "Return the per-sample/spot/filter/n_scans plan that "
                "Data Collection executes against. Synthesizes from "
                "ExperimentPlan.plan_json plus SamplePosition rows "
                "(filter_count = xas_filter, counts_per_sec = "
                "survey_counts_per_sec). planned_scans_total comes "
                "from plan_json when set, falling back to xas_reps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_holder_id": {"type": "string",
                                         "description": "Optional; defaults to the active holder."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_completed_scan",
            "description": (
                "Insert a CollectionScan row keyed by sample_id + "
                "scan_number after a successful run_xas (or sibling "
                "technique). Auto-fills `sample_id` from the active "
                "sample in plan_json, `scan_number` from "
                "get_scan_number, and `spec_datafile` from "
                "get_current_datafile when omitted. The scan row is "
                "what makes the run visible to the Planner's "
                "convergence analysis and to the orchestrator's plan "
                "summary (recent_plots lookup). Justification is "
                "required so the action is auditable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
                    "sample_id": {
                        "type": "string",
                        "description": (
                            "Sample to credit the scan to. Defaults to "
                            "the active sample in plan_json (explicit "
                            "active_sample_id, else the lowest-queue-"
                            "order sample whose status is not "
                            "done/skipped)."
                        ),
                    },
                    "scan_number": {
                        "type": "integer",
                        "description": (
                            "SPEC scan number. Defaults to the latest "
                            "scan number from get_scan_number."
                        ),
                    },
                    "technique": {
                        "type": "string",
                        "enum": ["xas", "herfd", "rixs", "vtc"],
                        "default": "xas",
                        "description": "Acquisition technique. Default 'xas'.",
                    },
                    "filter_setting": {
                        "type": "integer",
                        "description": "Filter bitmask used for the scan.",
                    },
                    "count_time": {
                        "type": "number",
                        "description": "Per-point count time in seconds.",
                    },
                    "spec_datafile": {
                        "type": "string",
                        "description": (
                            "SPEC datafile path or basename. Defaults "
                            "to get_current_datafile."
                        ),
                    },
                    "spot_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "0-based spot index within the sample. "
                            "Required for multi-spot samples so the "
                            "comprehensive plan can return per-spot "
                            "remaining reps."
                        ),
                    },
                },
                "required": ["justification"],
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
    # -----------------------------------------------------------------
    # CAT-9 · Data / analysis / plotting (formerly definitions.py)
    # -----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_latest_scan",
            "description": "Get the most recently processed scan. Returns metadata and a data preview.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scans",
            "description": "List processed scans with metadata (file name, scan number, command, counters, number of points).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of scans to list (default 20)",
                        "default": 20,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_scan",
            "description": "Read a processed scan's data and metadata. Use list_scans first to find available file_name and scan_number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_log_entries",
            "description": "Get the most recent entries from the beamline control logs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "integer",
                        "description": "Number of log lines to return (default 100)",
                        "default": 100,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": "Search the beamline control logs for a specific string or error message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The text to search for in logs"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 50)",
                        "default": 50,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_logs",
            "description": "List available log files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of logs to list (default 20)",
                        "default": 20,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_counter",
            "description": "Identify the 'active' fluorescence/absorption counter for a scan. Logic: ppboff if present, else the vortDT/vortDT2/vortDT3/vortDT4 with highest max counts, else I1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scan_deadtime",
            "description": "Get the dead time for a scan — the overhead time spent on motor moves, settling, and communication vs actual detector acquisition. Returns wall-clock duration, acquisition time, dead time in seconds, and dead time as a percentage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "normalize_scan",
            "description": "Edge-step normalize a scan: divide signal by I0, then scale so pre-edge is 0 and post-edge is 1. Returns the normalized data array.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                    "counter": {
                        "type": "string",
                        "description": "Counter to normalize. Auto-detected if omitted.",
                    },
                    "normalize_by": {
                        "type": "string",
                        "description": "Counter to divide by before edge-step normalization (default: I0)",
                        "default": "I0",
                    },
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "average_scans",
            "description": (
                "Average all energy scans in a SPEC file after edge-step normalization. "
                "Returns mean and standard deviation across scans. If file_name is omitted, "
                "uses the most recent file with >1 energy scan. Optionally crops the average "
                "to a numeric energy window [e_min, e_max] in eV, and supports SNR-aware "
                "inverse-variance weighting across reps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file with >1 energy scan.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower energy bound (eV) for the returned average. Optional; if both e_min and e_max are given, the average is cropped to that window. Normalization is still done on the full scan.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper energy bound (eV) for the returned average.",
                    },
                    "weighting": {
                        "type": "string",
                        "enum": ["equal", "inverse_variance"],
                        "default": "equal",
                        "description": (
                            "'equal' = unweighted mean (default). 'inverse_variance' = weight each "
                            "rep by 1/sigma_i^2 where sigma_i is estimated from that rep's post-edge "
                            "baseline std. Use inverse_variance when reps come from spots with very "
                            "different signal levels and you want SNR-optimal averaging."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_convergence",
            "description": (
                "Check if repeated scans have converged using cosine similarity metrics. "
                "Reports per-scan similarity to the mean, cumulative convergence, and standard error. "
                "Cosine similarity is amplitude-dominated; the post-edge plateau (defined "
                "to be ~1.0 by edge-step normalization) dominates the metric. You must pass "
                "e_min/e_max to focus on the dynamic part of the spectrum."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window to analyze. Identify the feature on the averaged spectrum first, then pass its bounds.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window to analyze.",
                    },
                },
                "required": ["e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_efficiency",
            "description": (
                "Comprehensive scan repetition efficiency report. Includes convergence, CV analysis, "
                "rate-based and counts-based Poisson floor comparison, optimal scan count recommendation, "
                "and a verdict (needs_more / reasonable / marginal / wasteful). "
                "e_min/e_max bounds are required — whole-spectrum mode averages dynamic content with "
                "normalization-defined plateaus and produces structurally optimistic verdicts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window.",
                    },
                    "include_poisson_floor": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "If true (default), also compute the absolute counts-based Poisson floor "
                            "from the raw active counter. Result includes counts_poisson_floor_pct and "
                            "cv_vs_floor_ratio: ratio ~1 means at the floor (more reps still help "
                            "as 1/sqrt(n)); ratio >>1 means systematics-limited (more reps won't help)."
                        ),
                    },
                },
                "required": ["e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_feature_evolution",
            "description": (
                "Per-rep scalar trace + convergence verdict for a feature defined by an energy window "
                "and a statistic. The agent identifies a feature on the spectrum (white-line peak, "
                "pre-edge shoulder, dip between oscillations, etc.) and passes the numeric eV bounds "
                "and the statistic that captures it. Returns running mean, running SEM, and a verdict "
                "(converged / marginal / needs_more) for that scalar. This is the publication-quality "
                "test: the feature SEM should be a small fraction of its mean and the running mean "
                "should be flat rep-over-rep."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name.",
                    },
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window. REQUIRED.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window. REQUIRED.",
                    },
                    "statistic": {
                        "type": "string",
                        "enum": ["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                        "default": "max",
                        "description": (
                            "Reduction over the window. 'max' = white-line height. 'argmax' = white-line "
                            "energy / edge position. 'integral' = peak area. 'min' / 'argmin' = a dip's "
                            "value / position. 'height' = max - min in window (peak prominence). 'mean' / "
                            "'median' = average value (use when the feature is a plateau)."
                        ),
                    },
                    "sem_threshold_frac": {
                        "type": "number",
                        "default": 0.01,
                        "description": (
                            "Target final SEM as a fraction of the running mean. 0.01 (1%) is the "
                            "default for publication-quality on a prominent feature; tighten to 0.005 "
                            "for very small features driving a result."
                        ),
                    },
                    "drift_threshold_frac": {
                        "type": "number",
                        "default": 0.01,
                        "description": "Step-to-step running-mean drift target as fraction of the latest mean.",
                    },
                },
                "required": ["file_name", "e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "group_scans_by_spot",
            "description": (
                "Cluster a file's scans by sample spot using the recorded Sx/Sy/Sz motor positions. "
                "Two scans are the same spot if their Sx, Sy, Sz all agree within tol_mm. Useful "
                "before convergence analysis when reps came from multiple spots — between-spot "
                "differences can pollute whole-file CV. Pair with analyze_per_spot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "tol_mm": {
                        "type": "number",
                        "default": 0.05,
                        "description": "Position tolerance in mm for grouping. Default 0.05 mm.",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_per_spot",
            "description": (
                "Run the full convergence/efficiency analysis SEPARATELY for each sample spot in "
                "the file (grouped by Sx/Sy/Sz), and report a between-spot vs within-spot "
                "heterogeneity F-statistic. F~1 = spots agree (safe to combine); F>>1 = spots "
                "disagree beyond shot noise (the combined average is a population mean, not a "
                "single chemistry — more reps won't fix it). Pass numeric e_min/e_max for the "
                "feature you care about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {
                        "type": "number",
                        "description": "Lower bound (eV) of the feature window. Strongly recommended.",
                    },
                    "e_max": {
                        "type": "number",
                        "description": "Upper bound (eV) of the feature window.",
                    },
                    "tol_mm": {
                        "type": "number",
                        "default": 0.05,
                        "description": "Position tolerance in mm for grouping.",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_scan",
            "description": "Generate and display a plot of scan data. Use this by default when the user wants to see a plot. The plot is shown directly to the user. Use list_scans to find available file_name and scan_number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The SPEC source file name"},
                    "scan_number": {"type": "integer", "description": "The scan number within the file"},
                    "counter": {
                        "type": "string",
                        "description": "Counter to plot (e.g. 'I0', 'vortDT'). If omitted, auto-detects the active counter.",
                    },
                    "normalize_by": {
                        "type": "string",
                        "description": "Optional counter to normalize by (e.g. 'I0')",
                    },
                },
                "required": ["file_name", "scan_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_averaged_scans",
            "description": "Plot averaged energy scans for multiple samples overlaid on one plot. Each sample is edge-step normalized and averaged, then plotted with standard deviation shading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of SPEC file names (one per sample) to compare.",
                    }
                },
                "required": ["file_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_scan_stack",
            "description": (
                "Overlay all reps of one sample on a single axis, color-progressed by rep order. "
                "Use to visually judge whether reps scatter symmetrically around a stable mean "
                "(converged), are still drifting in one direction (more reps needed or evolving "
                "sample), or are being burned away (damage). Pass numeric e_min/e_max to crop to "
                "the feature you care about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional but strongly recommended."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_first_half_vs_second_half",
            "description": (
                "Compare the average of the first half of reps to the second half, with SEM bands. "
                "Reports max |Δ|/SEM. <2σ: halves agree, sample is stationary. >3σ at any feature: "
                "the halves disagree, more reps may not help (drift, damage, or heterogeneity). "
                "This is the strongest single-glance test for whether the sample is publication-clean."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_running_average",
            "description": (
                "Plot the running average across reps as it evolves (one line per cumulative subset, "
                "color-progressed by rep #), with the final ±SEM band. Shows whether the running "
                "mean is still changing rep-over-rep at the feature of interest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). Optional."},
                    "e_max": {"type": "number", "description": "Upper bound (eV)."},
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_feature_evolution",
            "description": (
                "Plot a single per-rep scalar (the chosen statistic over [e_min, e_max]) versus rep "
                "number, with running mean and ±SEM band. The visual companion to "
                "analyze_feature_evolution. Use to confirm a feature has flatlined; a still-trending "
                "trace means the feature is not yet converged regardless of whole-spectrum verdicts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "SPEC file name."},
                    "e_min": {"type": "number", "description": "Lower bound (eV). REQUIRED."},
                    "e_max": {"type": "number", "description": "Upper bound (eV). REQUIRED."},
                    "statistic": {
                        "type": "string",
                        "enum": ["max", "min", "mean", "median", "integral", "argmax", "argmin", "height"],
                        "default": "max",
                        "description": "Reduction over the window. See analyze_feature_evolution for guidance.",
                    },
                },
                "required": ["file_name", "e_min", "e_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_data",
            "description": "General-purpose plotting tool. Plot any data as a line chart. Use this to visualize results from other tools (e.g. read_scan). Supports multiple series on one plot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "X-axis values.",
                    },
                    "y": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Y-axis values (same length as x).",
                    },
                    "y2": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional second series Y values.",
                    },
                    "y3": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional third series Y values.",
                    },
                    "y4": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional fourth series Y values.",
                    },
                    "xlabel": {"type": "string", "description": "X-axis label."},
                    "ylabel": {"type": "string", "description": "Y-axis label."},
                    "title": {"type": "string", "description": "Plot title."},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Legend labels for each series.",
                    },
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List non-SPEC files in the scan directory (macros, configs, text files).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (default: *). Example: *.mac",
                        "default": "*",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the scan directory. Use list_files to discover available files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the scan directory (e.g. run01.mac)",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_summary",
            "description": "Save a conversation summary as a timestamped .txt file in the scan directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The summary text to write.",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_macro",
            "description": "Save an edited macro as a new .mac file in the scan directory. The file is saved with a _heroic_<date> suffix to preserve the original.",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_name": {
                        "type": "string",
                        "description": "Original macro filename (e.g. run01.mac).",
                    },
                    "content": {
                        "type": "string",
                        "description": "The edited macro content.",
                    },
                },
                "required": ["original_name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_plan",
            "description": (
                "Save a markdown plan to the project's logs/plans/ directory. Use this at the "
                "start of a beamline-optimization session (or any multi-step task) to "
                "persist the step-by-step plan you generated, so future sessions can "
                "review what was attempted and why."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "Filename for the plan. Must end with .md and contain only "
                            "alphanumerics, underscore, hyphen, dot. No path separators "
                            "or directory traversal."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Markdown body of the plan.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "If false (default), refuse to write when the file already "
                            "exists. Set true to overwrite an existing plan."
                        ),
                        "default": False,
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_motor_config",
            "description": "Get SPEC motor configuration from the config file. Shows controller, steps/unit, slew rate, flags, mnemonic, and name for each motor. Motor index (MOTnnn) maps to the A[] array.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_counter_config",
            "description": "Get SPEC counter configuration from the config file. Shows controller, unit, channel, scale, flags, mnemonic, and name for each counter. Counter index (CNTnnn) maps to the S[] array.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_spec_macro",
            "description": (
                "Run a SPEC macro in a disposable, network-isolated sandbox container. "
                "Returns JSON with an `output` key containing the clean command result "
                "and a `log` key with the full session transcript (startup noise included). "
                "Use `output` for parsing; use `log` only for debugging. "
                "Each call is a cold start: no state persists between calls. "
                "Sim-only — does not affect real hardware. Always check `output` even "
                "on ok=True; SPEC sometimes exits 0 despite warnings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "macro": {
                        "type": "string",
                        "description": (
                            "SPEC macro source to evaluate. Single command, sequence, "
                            "or full def block. Do not include a trailing 'exit'."
                        ),
                    },
                    "preload": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional filenames under /usr/local/lib/spec.d/ to qdo "
                            "before running the macro (e.g. 'beamline_align.mac'). "
                            "Plain filenames only — no path components."
                        ),
                    },
                    "timeout_s": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 300,
                        "description": (
                            "Hard kill timeout for the SPEC run in seconds (default 30). "
                            "Sim mode skips real motion so most runs finish in under a second."
                        ),
                    },
                },
                "required": ["macro"],
            },
        },
    },
]

# Category map for the sidebar
AUTONOMY_TOOL_CATEGORIES = [
    ("CAT-0 Procedures", [
        "align_beamline", "align_xes_spectrometer", "run_sample_alignment",
        "run_collection", "select_element", "peak_mono_pitch",
        "calibrate_mono",
    ]),
    ("CAT-1 Motors", [
        "move_motor", "move_motor_relative", "read_motor_position",
        "read_all_positions",
    ]),
    ("CAT-2 Scans", [
        "run_motor_scan", "run_motor_scan_relative", "run_diagonal_scan",
        "run_xas", "run_emiss_scan", "fit_emission_peak",
    ]),
    ("CAT-3 Config", [
        "mv_energy", "shutter", "set_filter", "safely_remove_filters",
        "set_gain", "set_vortex_roi", "open_data_file", "plotselect",
    ]),
    ("CAT-4 Align Fallbacks", ["run_align_shortcut", "post_scan_move"]),
    ("CAT-5 Beam Diagnostic", [
        "mv_pinhole", "mv_plastic", "mv_knife_clear", "mv_knife_out",
        "measure_beam_size", "zero_pinhole",
        "small_beam", "big_beam", "xtal_align", "reset_gap", "set_m2_stripe",
        "get_anchor", "set_anchor", "tracking",
    ]),
    ("CAT-6 Beam", ["get_beam_size", "get_beam_status", "get_counts", "get_counter", "request_gap_ownership"]),
    ("CAT-7 State", ["get_element", "get_scan_number", "get_current_datafile", "get_plotselected_counter", "abort_current_scan"]),
    ("CAT-8 Orchestration", [
        "transition_phase", "request_human_intervention", "post_status_update",
        "log_status_assessment",
        "update_plan", "record_sample_progress", "get_plan",
        "get_experiment_config",
        "get_scans_since_last_plan_update", "get_scans_for_active_sample",
        "upload_sample_alignment_results",
        "upload_sample_survey_results", "get_comprehensive_collection_plan",
        "get_remaining_beamtime", "get_staff_guidance", "list_open_interventions",
        "recent_actions",
        "set_sample_time_budget", "set_holder_time_budget",
        "get_holder_time_budget",
        "set_experiment_end_time", "regenerate_plan",
        "record_completed_scan", "record_convergence_stats",
    ]),
    ("CAT-9 Data", [
        "get_latest_scan", "list_scans", "read_scan", "get_latest_log_entries",
        "search_logs", "list_logs", "get_active_counter", "get_scan_deadtime",
        "normalize_scan", "average_scans", "analyze_convergence",
        "analyze_efficiency", "analyze_feature_evolution",
        "group_scans_by_spot", "analyze_per_spot", "plot_averaged_scans",
        "plot_scan", "plot_scan_stack", "plot_first_half_vs_second_half",
        "plot_running_average", "plot_feature_evolution", "plot_data",
        "list_files", "read_file", "write_summary", "write_macro",
        "save_plan", "get_motor_config", "get_counter_config",
        "evaluate_spec_macro",
    ]),
]
