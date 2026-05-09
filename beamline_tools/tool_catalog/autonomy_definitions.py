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
                "is not moved, if nbrFilter <0 then filter motor isnt moved"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_J,
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
        "update_experiment_plan", "record_sample_progress", "get_plan",
        "get_experiment_config",
        "get_scans_since_last_plan_update", "get_scans_for_active_sample",
        "upload_sample_alignment_results",
        "upload_sample_survey_results", "get_comprehensive_collection_plan",
        "get_remaining_beamtime", "get_staff_guidance", "list_open_interventions",
        "recent_actions",
        "set_sample_time_budget", "set_holder_time_budget",
        "set_experiment_end_time", "regenerate_plan",
        "record_completed_scan",
    ]),
]
