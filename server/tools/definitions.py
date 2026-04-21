"""Tool definitions for BeamtimeHero.

TOOL_DEFINITIONS: Full schemas for MCP mode (10 tools).
CLI_TOOL_DEFINITION: Single run_command tool for CLI mode.
"""

TOOL_DEFINITIONS = [
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
            "description": "Average all energy scans in a SPEC file after edge-step normalization. Returns mean and standard deviation across scans. If file_name is omitted, uses the most recent file with >1 energy scan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file with >1 energy scan.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_convergence",
            "description": "Check if repeated scans have converged using cosine similarity metrics. Reports per-scan similarity to the mean, cumulative convergence, and standard error. Use this when the user asks 'do I have enough scans?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_efficiency",
            "description": "Comprehensive scan repetition efficiency report. Includes convergence, CV analysis, Poisson limit comparison, optimal scan count recommendation, and a verdict (needs_more / reasonable / marginal / wasteful).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SPEC file name. If omitted, uses the most recent file.",
                    }
                },
                "required": [],
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
            "name": "spec_command",
            "description": "Send a command to the running SPEC session. Allowed: wa — motor positions | pwd — current directory | fon — open files | get_S — counter values. Check the log file for output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command name: wa, pwd, fon, or get_S",
                        "enum": ["wa", "pwd", "fon", "get_S"],
                    }
                },
                "required": ["command"],
            },
        },
    },
]

# Single tool definition for CLI mode
CLI_TOOL_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a beamtimehero CLI command to query beamline data, logs, and plots. "
                "Start with 'beamtimehero --help' to discover available commands. "
                "Use 'beamtimehero <command> --help' to see options for a specific command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full CLI command string to execute (e.g. 'beamtimehero list-scans --limit 5')",
                    }
                },
                "required": ["command"],
            },
        },
    },
]
