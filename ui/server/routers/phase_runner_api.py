"""Per-phase agent runner + spectrometer-aligned flag API.

Replaces the master Start/Pause/Resume/Stop autonomy bar. Every phase
tile owns its own subprocess; the user clicks Run on the tile, the
backend spawns the corresponding scripts/<phase>-claude.sh, and the
tile flips to running.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from orchestration.agent import phase_runner
from orchestration.plan_store.session import (
    get_experiment,
    set_spectrometer_aligned,
)
from beamline_tools.spec_control import spec_cmd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/phase", tags=["phase"])


_TAIL_MAX_BYTES = 64 * 1024  # cap each poll's payload
_PROJ_BODY_MAX = 200          # truncate any single projected body to this many chars


def _truncate(s: str, n: int = _PROJ_BODY_MAX) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _summarize_tool_input(name: str, inp: dict) -> str:
    if not isinstance(inp, dict):
        return _truncate(str(inp))
    if name == "Bash":
        cmd = inp.get("command") or ""
        return _truncate(cmd, 160)
    # Generic: keep just the keys + short values
    pieces = []
    for k, v in inp.items():
        sv = v if isinstance(v, str) else json.dumps(v, default=str)
        pieces.append(f"{k}={_truncate(sv, 60)}")
    return _truncate(" ".join(pieces), 160)


def _project_log_line(line: str) -> str | None:
    """Fold one raw JSONL log line into a one-line operator-readable
    display. Return None to drop the line entirely.

    Drops: stream_event chunks (per-token deltas), rate-limit events,
    status:requesting heartbeats, task_started/notification (redundant
    with the tool_use/tool_result we already keep), and assistant
    thinking blocks.
    """
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except (ValueError, TypeError):
        return None  # malformed/partial line — drop silently

    t = ev.get("type")
    if t in ("stream_event", "rate_limit_event"):
        return None

    if t == "system":
        sub = ev.get("subtype")
        if sub == "status" or sub in ("task_started", "task_notification"):
            return None
        if sub == "init":
            sid = (ev.get("session_id") or "")[:8]
            model = ev.get("model") or ""
            return f"[sys]   init  session={sid}  model={model}"
        return f"[sys]   {sub or 'event'}"

    if t == "assistant":
        msg = ev.get("message") or {}
        blocks = msg.get("content") or []
        if not blocks:
            return None
        last = blocks[-1]
        bt = last.get("type")
        if bt == "thinking":
            return None
        if bt == "text":
            txt = (last.get("text") or "").strip()
            return f"...     {_truncate(txt)}" if txt else None
        if bt == "tool_use":
            tname = last.get("name") or ""
            summary = _summarize_tool_input(tname, last.get("input") or {})
            return f">       {tname}: {summary}"
        return None

    if t == "user":
        msg = ev.get("message") or {}
        blocks = msg.get("content") or []
        if not blocks:
            return None
        last = blocks[-1]
        if last.get("type") != "tool_result":
            return None
        is_err = bool(last.get("is_error", False))
        content = last.get("content")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        elif not isinstance(content, str):
            content = json.dumps(content, default=str)
        marker = "<!>    " if is_err else "<       "
        return f"{marker}{_truncate(content)}"

    if t == "result":
        sub = ev.get("subtype") or ""
        turns = ev.get("num_turns")
        cost = ev.get("total_cost_usd") or ev.get("cost_usd")
        bits = [f"[done]  {sub}"]
        if turns is not None:
            bits.append(f"turns={turns}")
        if cost is not None:
            bits.append(f"cost=${cost}")
        return "  ".join(bits)

    return None


def _project_chunk(text: str) -> str:
    out_lines = []
    for raw in text.splitlines():
        proj = _project_log_line(raw)
        if proj is not None:
            out_lines.append(proj)
    if not out_lines:
        return ""
    return "\n".join(out_lines) + "\n"


def _tail_file(path: str | None, offset: int, projected: bool = False) -> dict:
    """Read at most _TAIL_MAX_BYTES from `path` starting at `offset`.

    Returns {path, offset, content, eof} where the new offset is the
    file's end-of-file position after the read. If `offset` is past
    EOF (file rotated/truncated), reset to 0 and re-read from start.

    If `projected=True`, the JSONL stream is folded into a compact
    operator-readable form (drops streaming token deltas, thinking
    blocks, status heartbeats; collapses long tool_result bodies).
    The returned `offset` advances only past the last complete line so
    a partial JSON line at the chunk tail is retried on the next poll.
    """
    if not path or not os.path.exists(path):
        return {"path": path, "offset": 0, "content": "", "eof": 0}
    size = os.path.getsize(path)
    if offset > size:
        offset = 0
    end = min(size, offset + _TAIL_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(end - offset)
    if not projected:
        return {
            "path": path,
            "offset": end,
            "content": chunk.decode("utf-8", errors="replace"),
            "eof": size,
        }
    # Project complete lines only — leave a trailing partial line for
    # the next poll so we never feed half a JSON object to the parser.
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return {"path": path, "offset": offset, "content": "", "eof": size}
    complete = chunk[: last_nl + 1].decode("utf-8", errors="replace")
    return {
        "path": path,
        "offset": offset + last_nl + 1,
        "content": _project_chunk(complete),
        "eof": size,
    }


@router.post("/run/{slug}")
async def run_phase(slug: str):
    try:
        info = phase_runner.start(slug)
    except ValueError as e:
        # 409 if already running; 400/404 for unknown slug or missing script.
        msg = str(e)
        code = 409 if "already running" in msg else 400
        raise HTTPException(code, msg)
    return {"ok": True, **info}


@router.post("/kill/{slug}")
async def kill_phase(slug: str):
    try:
        info = phase_runner.kill(slug)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, **info}


@router.post("/kill_all")
async def kill_all_phases():
    """SIGTERM every running phase agent. Used by the autonomy bar's
    Stop agents button."""
    killed = phase_runner.kill_all()
    return {"ok": True, "killed": killed, "count": len(killed)}


@router.get("/run_status")
async def run_status():
    return {"phases": phase_runner.status_all()}


@router.post("/spectrometer_aligned")
async def post_spectrometer_aligned(payload: dict):
    """Set/clear the operator-confirmed spectrometer-alignment flag."""
    experiment_id = (
        (payload or {}).get("experiment_id")
        or spec_cmd.get_experiment_id()
    )
    if not experiment_id:
        raise HTTPException(400, "experiment_id required")
    aligned = bool((payload or {}).get("aligned", True))
    exp = set_spectrometer_aligned(experiment_id, aligned)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return {"ok": True, "experiment_id": experiment_id, "aligned": exp.spectrometer_aligned}


@router.get("/log_tail")
async def log_tail(
    slug: str | None = None,
    offset: int = 0,
    projected: bool = True,
):
    """Tail the most recent phase agent log.

    If `slug` is given, tails that phase's most recent log. Otherwise
    auto-picks the most recently active slug (running > finished).
    Returns {slug, path, offset, content, eof} so the frontend can
    advance its local offset and detect log rotation.

    Defaults to a projected (filtered, human-readable) view of the
    JSONL agent log. Pass `projected=false` to get the raw JSONL.
    """
    target = slug or phase_runner.latest_active_slug()
    if target is None:
        return {"slug": None, "path": None, "offset": 0, "content": "", "eof": 0}
    path = phase_runner.get_log_path(target)
    out = _tail_file(path, offset, projected=projected)
    out["slug"] = target
    return out


@router.get("/spectrometer_aligned")
async def get_spectrometer_aligned(experiment_id: str):
    exp = get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return {
        "experiment_id": experiment_id,
        "aligned": bool(getattr(exp, "spectrometer_aligned", False)),
        "mono_crystal": exp.mono_crystal,
    }
