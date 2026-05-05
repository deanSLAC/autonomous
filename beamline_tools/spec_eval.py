"""Sandbox evaluation of SPEC macros via the spec-eval Docker API.

Wraps the spec-eval HTTP service to let the LLM validate SPEC macro code
in a disposable, network-isolated container before recommending it.
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

import requests

from beamline_tools.config import SPEC_EVAL_URL

logger = logging.getLogger(__name__)

DEFAULT_API_URL = SPEC_EVAL_URL
_HTTP_TIMEOUT = 600  # must comfortably exceed SPEC's own timeout

# Bypass the HTTP proxy for all spec-eval traffic (always localhost).
_session = requests.Session()
_session.trust_env = False


class SpecEvalResult(TypedDict):
    ok: bool
    exit_code: int | None
    timed_out: bool
    output: str          # clean command output (between SPEC_EVAL markers)
    log: str             # full session log including startup/teardown noise
    duration_s: float | None
    run_id: str | None
    error: str | None
    reply: str | None           # SV_REPLY payload (TCP mode only)
    output_complete: bool | None


def _error_result(message: str) -> SpecEvalResult:
    return SpecEvalResult(
        ok=False,
        exit_code=None,
        timed_out=False,
        output="",
        log="",
        duration_s=None,
        run_id=None,
        error=message,
        reply=None,
        output_complete=None,
    )


def evaluate_spec_macro(
    macro: str,
    preload: list[str] | None = None,
    timeout_s: int = 30,
    api_url: str = DEFAULT_API_URL,
    mode: str = "screen",
) -> SpecEvalResult:
    """Run a SPEC macro in a disposable sandbox container and return the log.

    Never raises — failures are reported via the ``error`` field so the
    agent can handle outcomes inline.
    """
    payload: dict[str, Any] = {
        "macro": macro,
        "preload": preload or [],
        "timeout_s": timeout_s,
    }
    endpoint = "/evaluate_tcp" if mode == "tcp" else "/evaluate"
    url = api_url.rstrip("/") + endpoint

    try:
        resp = _session.post(url, json=payload, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as e:
        logger.warning("spec-eval transport error: %s", e)
        return _error_result(f"transport error: {e}")

    if resp.status_code >= 500:
        return _error_result(f"server error {resp.status_code}: {resp.text[:500]}")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return _error_result(f"bad request ({resp.status_code}): {detail}")

    data = resp.json()
    timed_out = bool(data.get("timed_out"))
    exit_code = data.get("exit_code")
    return SpecEvalResult(
        ok=(exit_code == 0 and not timed_out),
        exit_code=exit_code,
        timed_out=timed_out,
        output=data.get("output", ""),
        log=data.get("log", ""),
        duration_s=data.get("duration_s"),
        run_id=data.get("run_id"),
        error=None,
        reply=data.get("reply"),
        output_complete=data.get("output_complete"),
    )
