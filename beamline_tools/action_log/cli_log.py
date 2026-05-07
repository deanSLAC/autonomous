"""beamtimehero CLI invocation log writer.

One row per `beamtimehero` call, written from `scripts/beamtimehero:main()`
after dispatch. Failure-tolerant by design: any exception in the writer is
swallowed so the CLI's exit code and stdout are never affected.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional, Sequence

from beamline_tools.action_log.models import CliInvocationLog
from beamline_tools.action_log.session import get_session

logger = logging.getLogger(__name__)


def record_cli_invocation(
    *,
    argv: Sequence[str],
    tree: Optional[str],
    leaf: Optional[str],
    tool_name: Optional[str],
    justification: Optional[str],
    exit_code: int,
    latency_ms: int,
    stdout_tail: Optional[str],
    error_message: Optional[str],
    spec_mock: Optional[int],
) -> None:
    """Insert one CliInvocationLog row. Never raises."""
    try:
        row = CliInvocationLog(
            argv_json=json.dumps(list(argv)),
            tree=tree,
            leaf=leaf,
            tool_name=tool_name,
            justification=justification,
            exit_code=int(exit_code),
            latency_ms=int(latency_ms),
            stdout_tail=stdout_tail,
            error_message=error_message,
            spec_mock=spec_mock,
            pid=os.getpid(),
        )
        with get_session() as session:
            session.add(row)
            session.commit()
    except Exception as e:  # noqa: BLE001 — logging must never break the CLI
        logger.warning("cli_log write failed: %s", e)
