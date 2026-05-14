"""Single-tool definition for CLI (progressive discovery) mode.

Exposed to the LLM in CLI mode as one `run_command` tool that runs
`beamtimehero <command>` subcommands. The full schemas for individual
tools live in `definitions.py`.
"""

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
