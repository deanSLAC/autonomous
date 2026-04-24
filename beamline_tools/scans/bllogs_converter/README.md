# BL15-2 SPEC Log Converter

Parses SPEC session log files from beamline 15-2 at SSRL, extracts user commands and detects errors, and stores results in PostgreSQL.

## What it does

1. Reads log files matching `log__*` from `BL_LOGS_DIR`
2. Parses SPEC session commands (lines matching `N.SPEC> command`) — ignores XRS40 and other sessions
3. Extracts timestamps from `#C` comment lines and standalone timestamp lines
4. Records each command to the `"BL15-2_log_commands"` table with its timestamp
5. Runs error detection on each command's output (LLM-based or regex fallback)
6. Records detected errors to the `"BL15-2_log_errors"` table
7. Tracks processing progress per file (byte offset) so only new content is processed on each run

## Top-level script

The converter is invoked as a Python module:

```bash
python -m bllogs_converter
```

This is the script that should be called every 60 seconds. It will:
- Scan all log files in `BL_LOGS_DIR`
- For each file, check if new content has been appended since the last run
- Parse only the new content, extract SPEC commands, detect errors
- Write results to PostgreSQL
- Update the byte-offset progress tracker

Typical runtime is under a second when no new content exists (just DB lookups for progress).

## CLI reference

```
python -m bllogs_converter [--file PATH] [--logs-dir DIR] [--no-llm] [--reprocess] [--dry-run]
```

| Flag | Description |
|------|-------------|
| (no flags) | Process all log files under `BL_LOGS_DIR`, incrementally |
| `--file PATH` | Process a single log file |
| `--logs-dir DIR` | Override the log file directory |
| `--no-llm` | Skip LLM error detection, use regex patterns only |
| `--reprocess` | Reset progress and reprocess files from the beginning |
| `--dry-run` | Parse files but don't write to the database |

## Database tables

### `"BL15-2_log_commands"`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Auto-incrementing ID |
| log_file | TEXT | Log file name (e.g. `log__12-04-2025`) |
| command_number | INTEGER | The prompt number from the log (e.g. 42 from `42.SPEC>`) |
| command_text | TEXT | The command issued (e.g. `ct`, `dscan th -0.5 0.5 50 1`) |
| timestamp | TIMESTAMP | Approximate time, from the most recent preceding timestamp in the log |
| inserted_at | TIMESTAMP | When this record was inserted |

### `"BL15-2_log_errors"`
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Auto-incrementing ID |
| log_file | TEXT | Log file name |
| command_text | TEXT | The command that produced the error |
| error_description | TEXT | Description of the error |
| timestamp | TIMESTAMP | Approximate time of the error |
| inserted_at | TIMESTAMP | When this record was inserted |

### `"BL15-2_log_file_progress"`
| Column | Type | Description |
|--------|------|-------------|
| log_file | TEXT PK | Log file name |
| bytes_processed | BIGINT | Byte offset up to which this file has been processed |
| last_processed_at | TIMESTAMP | When this file was last processed |

## Environment variables

Same as the main application — configured in the pod via Flux:

| Variable | Default | Description |
|----------|---------|-------------|
| `BL_LOGS_DIR` | `/sdf/group/ssrl/isaac/data/logs` | Directory containing log files |
| `DB_HOST` | `isaac-pgbouncer.isaac-psql.svc.cluster.local` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `bl152` | Database name |
| `DB_USER` | `bl152` | Database user |
| `DB_PASSWORD` | (none) | Database password |
| `API_KEY` | (none) | Stanford AI Gateway API key (for LLM error detection) |

## Project structure

| File | Purpose |
|------|---------|
| `converter.py` | CLI entry point: arg parsing, file dispatch, orchestration |
| `log_parser.py` | Log file parsing: extract SPEC commands and timestamps |
| `error_checker.py` | Error detection: LLM-based (primary) + regex fallback |
| `db.py` | PostgreSQL operations: table creation, inserts, progress tracking |
