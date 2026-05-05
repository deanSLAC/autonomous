"""GNU-screen transport for SPEC sessions.

Stuffs commands into a `screen` session running spec interactively, then
hardcopies the buffer and watches for the `N.SPEC>` prompt to detect
completion. This is the legacy fallback transport — `tcp_client` is the
preferred path. Selection between the two happens in `spec_cmd.dispatch`.

This module knows nothing about the mock simulator or the TCP transport;
it always calls real `screen` subprocesses. The router in `spec_cmd.py`
is responsible for short-circuiting to the mock when `SPEC_MOCK=1`.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time

from beamline_tools.config import (
    SPEC_POLL_INTERVAL_S,
    SPEC_PROMPT_REGEX,
    SPEC_SCREEN_NAME,
)
from beamline_tools.spec_control.transport import DispatchResult

logger = logging.getLogger(__name__)

_PROMPT_RE = re.compile(SPEC_PROMPT_REGEX)


def dispatch(
    spec_string: str,
    *,
    timeout_s: float = 1800.0,
    settle_sleep_s: float = 0.5,
) -> DispatchResult:
    """Inject a SPEC string into the screen session and poll for the prompt."""
    started = time.time()

    result = subprocess.run(["screen", "-list"], capture_output=True, text=True)
    if SPEC_SCREEN_NAME not in result.stdout:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"screen session '{SPEC_SCREEN_NAME}' not running",
            transport="screen",
        )

    try:
        subprocess.run(
            ["screen", "-S", SPEC_SCREEN_NAME, "-X", "stuff", f"{spec_string}\n"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"screen stuff failed: {e}",
            transport="screen",
        )

    # Short settle before first capture (many motor moves return <1s)
    time.sleep(settle_sleep_s)

    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".screen", mode="w")
    tmpfile.close()
    try:
        prompt_seen = False
        last_capture = ""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                subprocess.run(
                    ["screen", "-S", SPEC_SCREEN_NAME, "-X", "hardcopy", tmpfile.name],
                    capture_output=True, text=True, check=True, timeout=10,
                )
                with open(tmpfile.name, "r", errors="replace") as f:
                    last_capture = f.read()
            except Exception as e:  # capture failure is non-fatal; keep trying
                logger.warning("hardcopy failed: %s", e)

            if _has_prompt(last_capture):
                prompt_seen = True
                break
            time.sleep(SPEC_POLL_INTERVAL_S)

        return DispatchResult(
            ok=prompt_seen,
            output=last_capture,
            prompt_seen=prompt_seen,
            elapsed_s=time.time() - started,
            error=None if prompt_seen else "timeout waiting for SPEC> prompt",
            transport="screen",
        )
    finally:
        try:
            os.unlink(tmpfile.name)
        except OSError:
            pass


def _has_prompt(buf: str) -> bool:
    for line in reversed([l.rstrip() for l in buf.splitlines()]):
        if not line:
            continue
        if _PROMPT_RE.match(line):
            return True
        # first non-empty line is not a prompt → still running
        return False
    return False


def abort_current() -> bool:
    """Stuff a literal ^C into the screen session."""
    try:
        subprocess.run(
            ["screen", "-S", SPEC_SCREEN_NAME, "-X", "stuff", "\x03"],
            capture_output=True, text=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error("abort failed: %s", e)
        return False
