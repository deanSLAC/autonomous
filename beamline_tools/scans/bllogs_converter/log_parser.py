"""Parse SPEC session log files, extracting commands and timestamps.

Only processes lines from SPEC sessions (N.SPEC> prompts).
XRS40 and other session types are ignored.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

SPEC_PROMPT_RE = re.compile(r'^(\d+)\.SPEC>\s*(.*)')
OTHER_PROMPT_RE = re.compile(r'^\d+\.\w+>\s')
TIMESTAMP_COMMENT_RE = re.compile(r'^#C\s+(\w{3}\s+\w{3}\s+\d{2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\.')
TIMESTAMP_STANDALONE_RE = re.compile(r'^(\w{3}\s+\w{3}\s+\d{2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s*$')
TIMESTAMP_FORMAT = "%a %b %d %H:%M:%S %Y"


@dataclass
class CommandChunk:
    """A single SPEC command and its output."""
    command_number: int
    command_text: str
    output_lines: list = field(default_factory=list)
    timestamp: Optional[datetime] = None
    raw_text: str = ""


def parse_timestamp(line: str) -> Optional[datetime]:
    """Try to parse a timestamp from a log line."""
    m = TIMESTAMP_COMMENT_RE.match(line)
    if m:
        try:
            return datetime.strptime(m.group(1), TIMESTAMP_FORMAT)
        except ValueError:
            return None
    m = TIMESTAMP_STANDALONE_RE.match(line.strip())
    if m:
        try:
            return datetime.strptime(m.group(1), TIMESTAMP_FORMAT)
        except ValueError:
            return None
    return None


def parse_log_text(text: str) -> List[CommandChunk]:
    """Parse a block of log text and return SPEC command chunks.

    Tracks timestamps globally (across all session types) but only
    captures command chunks from SPEC sessions.
    """
    lines = text.split('\n')
    chunks = []
    current_chunk = None
    current_timestamp = None
    in_spec_block = False

    for line in lines:
        # Check for timestamps in any line
        ts = parse_timestamp(line)
        if ts is not None:
            current_timestamp = ts

        # Check for a SPEC prompt
        spec_match = SPEC_PROMPT_RE.match(line)
        if spec_match:
            # Finalize previous chunk
            if current_chunk is not None:
                current_chunk.raw_text = current_chunk.command_text + '\n' + '\n'.join(current_chunk.output_lines)
                chunks.append(current_chunk)

            cmd_num = int(spec_match.group(1))
            cmd_text = spec_match.group(2).strip()
            current_chunk = CommandChunk(
                command_number=cmd_num,
                command_text=cmd_text,
                timestamp=current_timestamp,
            )
            in_spec_block = True
            continue

        # Check for a non-SPEC prompt (e.g. XRS40) — ends current SPEC block
        if OTHER_PROMPT_RE.match(line):
            if current_chunk is not None:
                current_chunk.raw_text = current_chunk.command_text + '\n' + '\n'.join(current_chunk.output_lines)
                chunks.append(current_chunk)
                current_chunk = None
            in_spec_block = False
            continue

        # Accumulate output lines if we're inside a SPEC block
        if in_spec_block and current_chunk is not None:
            current_chunk.output_lines.append(line)

    # Finalize last chunk
    if current_chunk is not None:
        current_chunk.raw_text = current_chunk.command_text + '\n' + '\n'.join(current_chunk.output_lines)
        chunks.append(current_chunk)

    return chunks


def parse_log_file(filepath: str, start_offset: int = 0) -> Tuple[List[CommandChunk], int]:
    """Parse a log file from start_offset to end of file.

    Args:
        filepath: Path to the log file.
        start_offset: Byte offset to start reading from.

    Returns:
        (list of CommandChunk, new_offset) where new_offset is the
        byte position to resume from on the next run.
    """
    with open(filepath, 'rb') as f:
        f.seek(0, 2)
        file_size = f.tell()

        if start_offset >= file_size:
            return [], file_size

        f.seek(start_offset)
        raw = f.read()

    # If starting mid-file, discard first partial line
    if start_offset > 0:
        newline_pos = raw.find(b'\n')
        if newline_pos == -1:
            return [], file_size
        raw = raw[newline_pos + 1:]

    # Back up if last line is incomplete (no trailing newline)
    if raw and not raw.endswith(b'\n'):
        last_newline = raw.rfind(b'\n')
        if last_newline == -1:
            return [], start_offset  # entire chunk is one incomplete line
        new_offset = file_size - (len(raw) - last_newline - 1)
        raw = raw[:last_newline + 1]
    else:
        new_offset = file_size

    text = raw.decode(errors='replace')
    chunks = parse_log_text(text)
    return chunks, new_offset
