"""Read SPEC motor and counter configuration from the config file."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SPEC_CONFIG_PATH = Path("/usr/local/lib/spec.d/spec/config")


def _read_config() -> str:
    """Read the SPEC config file."""
    if not SPEC_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"SPEC config not found: {SPEC_CONFIG_PATH}")
    return SPEC_CONFIG_PATH.read_text()


def get_motor_config() -> str:
    """Extract the motor configuration section from the SPEC config file.

    Returns the header and all MOTnnn lines.
    """
    text = _read_config()
    lines = text.splitlines()

    collecting = False
    result = []
    for line in lines:
        if line.startswith("# Motor"):
            collecting = True
            result.append(line)
            continue
        if collecting:
            if line.startswith("# Counter"):
                break
            if line.startswith("MOT") or line.strip() == "":
                result.append(line)

    if not result:
        return "No motor configuration found in SPEC config."
    return "\n".join(result)


def get_counter_config() -> str:
    """Extract the counter configuration section from the SPEC config file.

    Returns the header and all CNTnnn lines.
    """
    text = _read_config()
    lines = text.splitlines()

    collecting = False
    result = []
    for line in lines:
        if line.startswith("# Counter"):
            collecting = True
            result.append(line)
            continue
        if collecting:
            if line.startswith("#"):
                break
            if line.startswith("CNT") or line.strip() == "":
                result.append(line)

    if not result:
        return "No counter configuration found in SPEC config."
    return "\n".join(result)
