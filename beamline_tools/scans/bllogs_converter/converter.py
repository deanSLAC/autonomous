"""SPEC log file converter.

Parses SPEC session log files, extracts user commands and detects errors,
stores results to PostgreSQL.

Usage:
    # Process all log files under default BL_LOGS_DIR
    python -m bllogs_converter

    # Process a single log file
    python -m bllogs_converter --file /path/to/log__12-04-2025

    # Skip LLM error detection (regex only)
    python -m bllogs_converter --no-llm

    # Reprocess from scratch
    python -m bllogs_converter --reprocess
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

from beamline_tools.scans.bl_config import BL_LOGS_DIR, LOG_FILE_PATTERN
from .db import (
    ensure_tables, get_file_progress, update_file_progress,
    reset_file_progress, insert_commands, insert_errors,
)
from .log_parser import parse_log_file
from .error_checker import check_for_errors


def process_file(filepath, *, use_llm=True, dry_run=False, reprocess=False):
    """Process a single log file incrementally.

    Returns:
        dict with {commands_found, errors_found, bytes_processed} or None if skipped.
    """
    log_file = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)

    if reprocess:
        if not dry_run:
            reset_file_progress(log_file)
        start_offset = 0
    else:
        start_offset = get_file_progress(log_file)

    if start_offset >= file_size:
        return None  # no new content

    # File was rotated/replaced — reprocess from beginning
    if start_offset > file_size:
        logger.warning("File %s shrank (stored offset %d > size %d), reprocessing from start.",
                        log_file, start_offset, file_size)
        if not dry_run:
            reset_file_progress(log_file)
        start_offset = 0

    logger.info("Processing %s from offset %d (file size %d)", log_file, start_offset, file_size)

    chunks, new_offset = parse_log_file(filepath, start_offset=start_offset)

    if not chunks:
        logger.info("No SPEC commands found in new content of %s", log_file)
        if not dry_run:
            update_file_progress(log_file, new_offset)
        return {"commands_found": 0, "errors_found": 0, "bytes_processed": new_offset}

    logger.info("Found %d SPEC command(s) in %s", len(chunks), log_file)

    # Prepare command records
    command_records = [
        {
            "log_file": log_file,
            "command_number": chunk.command_number,
            "command_text": chunk.command_text,
            "timestamp": chunk.timestamp,
        }
        for chunk in chunks
    ]

    if not dry_run:
        insert_commands(command_records)

    # Error detection
    detected_errors = check_for_errors(chunks, use_llm=use_llm)
    error_records = [
        {
            "log_file": log_file,
            "command_text": err.command_text,
            "error_description": err.error_description,
            "timestamp": chunks[err.chunk_index].timestamp if err.chunk_index < len(chunks) else None,
        }
        for err in detected_errors
    ]

    if error_records:
        logger.info("Detected %d error(s) in %s", len(error_records), log_file)
        if not dry_run:
            insert_errors(error_records)

    if not dry_run:
        update_file_progress(log_file, new_offset)

    return {
        "commands_found": len(chunks),
        "errors_found": len(error_records),
        "bytes_processed": new_offset,
    }


def process_all_logs(logs_dir=None, *, use_llm=True, dry_run=False, reprocess=False):
    """Process all log files matching LOG_FILE_PATTERN in logs_dir."""
    if logs_dir is None:
        logs_dir = str(BL_LOGS_DIR)

    if not os.path.isdir(logs_dir):
        logger.error("%s is not a directory.", logs_dir)
        sys.exit(1)

    import glob
    pattern = os.path.join(logs_dir, LOG_FILE_PATTERN)
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    if not files:
        logger.info("No log files matching '%s' found in %s.", LOG_FILE_PATTERN, logs_dir)
        return

    total_commands = 0
    total_errors = 0
    processed = 0
    skipped = 0

    for filepath in files:
        try:
            result = process_file(filepath, use_llm=use_llm, dry_run=dry_run, reprocess=reprocess)
            if result is None:
                skipped += 1
            else:
                processed += 1
                total_commands += result["commands_found"]
                total_errors += result["errors_found"]
        except Exception as e:
            logger.error("Error processing %s: %s", os.path.basename(filepath), e)

    logger.info("Done. Processed %d file(s), skipped %d unchanged. "
                "Total: %d commands, %d errors.",
                processed, skipped, total_commands, total_errors)


def main():
    parser = argparse.ArgumentParser(description="SPEC log file converter")
    parser.add_argument("--file", help="Path to a single log file to process")
    parser.add_argument(
        "--logs-dir",
        help=f"Directory containing log files (default: {BL_LOGS_DIR})",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM error detection, use regex patterns only",
    )
    parser.add_argument(
        "--reprocess", action="store_true",
        help="Reset progress and reprocess files from the beginning",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse files but don't write to the database",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.dry_run:
        ensure_tables()

    use_llm = not args.no_llm

    if args.file:
        if not os.path.isfile(args.file):
            logger.error("File not found: %s", args.file)
            sys.exit(1)
        result = process_file(args.file, use_llm=use_llm, dry_run=args.dry_run, reprocess=args.reprocess)
        if result:
            logger.info("Result: %s", result)
        else:
            logger.info("No new content to process.")
    else:
        process_all_logs(
            logs_dir=args.logs_dir,
            use_llm=use_llm,
            dry_run=args.dry_run,
            reprocess=args.reprocess,
        )
