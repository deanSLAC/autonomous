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
_DETAIL_BODY_MAX = 8 * 1024   # cap full body kept for the expandable detail view

_HOME = os.path.expanduser("~")
_PROJ_ROOT = "/usr/local/projects/autonomous"


def _short_path(p: str) -> str:
    """Collapse long absolute paths to the visually-meaningful tail.

    /usr/local/projects/autonomous/foo/bar.py     → <proj>/foo/bar.py
    /home/dean/.claude/projects/.../recent.json   → ~/.claude/projects/.../recent.json
    """
    if not isinstance(p, str) or not p:
        return p
    if p.startswith(_PROJ_ROOT):
        rest = p[len(_PROJ_ROOT):].lstrip("/")
        return f"<proj>/{rest}" if rest else "<proj>"
    if p.startswith(_HOME):
        rest = p[len(_HOME):].lstrip("/")
        return f"~/{rest}" if rest else "~"
    return p


def _shorten_paths_in_command(cmd: str) -> str:
    """Replace any /home/<user> or project-root prefix tokens inside a
    shell command with their tilde-equivalent so the meaningful args
    aren't drowned out by deep paths."""
    if not cmd:
        return cmd
    out = cmd.replace(_PROJ_ROOT, "<proj>")
    out = out.replace(_HOME, "~")
    return out


def _truncate(s: str, n: int = _PROJ_BODY_MAX) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _summarize_tool_input(name: str, inp: dict) -> str:
    if not isinstance(inp, dict):
        return _truncate(str(inp))
    if name == "Bash":
        cmd = inp.get("command") or ""
        return _truncate(_shorten_paths_in_command(cmd), 160)
    if name == "Read":
        path = inp.get("file_path") or inp.get("path") or ""
        offset = inp.get("offset")
        limit = inp.get("limit")
        tail = ""
        if offset is not None or limit is not None:
            o = offset or 0
            l = limit
            tail = f"  L{o + 1}–L{o + l}" if l else f"  L{o + 1}+"
        return _truncate(_short_path(str(path)) + tail, 160)
    if name in ("Edit", "Write"):
        path = inp.get("file_path") or ""
        return _truncate(_short_path(str(path)), 160)
    if name == "Grep":
        pat = inp.get("pattern") or ""
        path = inp.get("path") or ""
        glob = inp.get("glob") or ""
        bits = [f'"{_truncate(pat, 60)}"']
        if path:
            bits.append(f"in {_short_path(str(path))}")
        if glob:
            bits.append(f"({glob})")
        return _truncate(" ".join(bits), 160)
    # Generic: keep just the keys + short values
    pieces = []
    for k, v in inp.items():
        sv = v if isinstance(v, str) else json.dumps(v, default=str)
        pieces.append(f"{k}={_truncate(sv, 60)}")
    return _truncate(" ".join(pieces), 160)


def _json_shape_summary(obj) -> str:
    """One-line summary of a parsed JSON body, focused on shape.

    {a, b, c}                          → "{3 keys: a, b, c}"
    [obj, obj, obj]                    → "[3 items]"
    {ok, count, scans:[...]}           → "{ok=true, count=2, scans:[2]}"
    """
    if isinstance(obj, list):
        return f"[{len(obj)} items]" if obj else "[]"
    if not isinstance(obj, dict):
        return _truncate(str(obj), 120)
    if not obj:
        return "{}"
    bits = []
    for k, v in list(obj.items())[:4]:
        if isinstance(v, bool):
            bits.append(f"{k}={'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            bits.append(f"{k}={v}")
        elif isinstance(v, str):
            bits.append(f"{k}={_truncate(v, 30)!r}")
        elif isinstance(v, list):
            bits.append(f"{k}:[{len(v)}]")
        elif isinstance(v, dict):
            bits.append(f"{k}:{{{len(v)}}}")
        else:
            bits.append(f"{k}=…")
    more = "" if len(obj) <= 4 else f" +{len(obj) - 4} more"
    return _truncate("{" + ", ".join(bits) + more + "}", 160)


def _summarize_tool_result(content: str) -> str:
    """Fold a tool_result body into a short, operator-readable line.

    Tries to parse the content as JSON and dispatches by shape:
      - {"ok": true, "kind": "action", ...}      → ok action=<id>
      - {"ok": true, "kind": "read", ...}        → ok read
      - {"ok": false, "error": ...}              → ERR <message>
      - {"text": ..., "plot_path": ...}          → plot <summary> → <png>
      - [{"id": ..., ...}, ...] (steering rows)  → (N pending: id/text...)
      - "usage:..." help text                    → (help text, N lines)

    Falls back to a single-line truncation of the raw body otherwise.
    """
    if not content:
        return "(empty)"
    body = content.strip()

    # No-output sentinel from Bash → cleaner check mark.
    if body == "(Bash completed with no output)":
        return "(no output)"

    # Quick non-JSON paths first.
    if body.startswith("usage:"):
        n = body.count("\n") + 1
        return f"(help text, {n} lines)"

    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        # Plain string content. Collapse whitespace and truncate.
        return _truncate(body, 160)

    # JSON list — almost always a steering listing.
    if isinstance(obj, list):
        if not obj:
            return "(no rows)"
        if obj and isinstance(obj[0], dict) and "id" in obj[0] and "text" in obj[0]:
            heads = [
                f'{(r.get("id") or "")[:8]}/"{_truncate(r.get("text") or "", 30)}"'
                for r in obj[:3]
            ]
            more = "" if len(obj) <= 3 else f" +{len(obj) - 3} more"
            return f"({len(obj)} pending: {', '.join(heads)}{more})"
        return _json_shape_summary(obj)

    if not isinstance(obj, dict):
        return _truncate(str(obj), 160)

    # Plot tool: {"text": "Plot of ...", "plot_path": "/.../foo.png", ...}
    if "plot_path" in obj or ("text" in obj and "image_paths" in obj):
        text = (obj.get("text") or "").strip()
        path = obj.get("plot_path") or (obj.get("image_paths") or [""])[0]
        # Last path segment is enough — the leading dirs are always the same.
        short_path = path.rsplit("/", 1)[-1] if path else ""
        head = _truncate(text.splitlines()[0] if text else "", 100)
        return f"plot {head} → {short_path}".strip()

    # Standard spec wrapper: {"ok": bool, "kind": "...", ...}.
    if "ok" in obj:
        if obj.get("ok") is False:
            err = obj.get("error") or obj.get("message") or json.dumps(obj, default=str)
            return f"ERR {_truncate(str(err), 140)}"
        kind = obj.get("kind")
        if kind == "action":
            aid = (obj.get("action_id") or "")[:8]
            elapsed = obj.get("elapsed_s")
            tail = f" ({elapsed:.2f}s)" if isinstance(elapsed, (int, float)) else ""
            return f"ok action={aid}{tail}" if aid else f"ok action{tail}"
        if kind == "read":
            return "ok read"
        # Steering ack/defer/complete result: {"ok": true, "id": "...", ...}
        if "id" in obj:
            return f"ok id={(obj.get('id') or '')[:8]}"
        # Status post: {"posted": true, "via": "..."}
        if obj.get("posted"):
            return f"ok posted via {obj.get('via') or '?'}"
        return "ok"

    # Fallback: structural shape summary instead of a flattened JSON dump.
    return _json_shape_summary(obj)


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
        summary = _summarize_tool_result(content)
        marker = "<!>    " if is_err else "<       "
        return f"{marker}{summary}"

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


def _project_log_event(line: str) -> dict | None:
    """Structured-event variant of `_project_log_line`.

    Returns one of:
      {"kind": "tool_use",     "tool", "tool_use_id", "summary", "input"}
      {"kind": "tool_result",  "tool_use_id", "summary", "detail", "is_error"}
      {"kind": "assistant_text", "text"}
      {"kind": "system", "subtype", "text"}
      {"kind": "result", "subtype", "turns", "cost"}

    Returns None for noise (stream tokens, status heartbeats, thinking,
    rate-limit events). The frontend pairs tool_use ↔ tool_result by
    `tool_use_id` to render each call as a single card.
    """
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except (ValueError, TypeError):
        return None

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
            return {
                "kind": "system",
                "subtype": "init",
                "text": f"session={sid}  model={model}",
            }
        return {"kind": "system", "subtype": sub or "event", "text": ""}

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
            if not txt:
                return None
            return {"kind": "assistant_text", "text": txt}
        if bt == "tool_use":
            tname = last.get("name") or ""
            inp = last.get("input") or {}
            return {
                "kind": "tool_use",
                "tool": tname,
                "tool_use_id": last.get("id") or "",
                "summary": _summarize_tool_input(tname, inp),
                "input": inp,
            }
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
        detail = content or ""
        if len(detail) > _DETAIL_BODY_MAX:
            detail = detail[:_DETAIL_BODY_MAX] + f"\n… (+{len(content) - _DETAIL_BODY_MAX} bytes)"
        return {
            "kind": "tool_result",
            "tool_use_id": last.get("tool_use_id") or "",
            "summary": _summarize_tool_result(content),
            "detail": detail,
            "is_error": is_err,
        }

    if t == "result":
        return {
            "kind": "result",
            "subtype": ev.get("subtype") or "",
            "turns": ev.get("num_turns"),
            "cost": ev.get("total_cost_usd") or ev.get("cost_usd"),
        }

    return None


def _project_chunk_events(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in text.splitlines():
        ev = _project_log_event(raw)
        if ev is not None:
            out.append(ev)
    return out


def _tail_file(
    path: str | None,
    offset: int,
    projected: bool = False,
    structured: bool = False,
) -> dict:
    """Read at most _TAIL_MAX_BYTES from `path` starting at `offset`.

    Returns {path, offset, content, eof} where the new offset is the
    file's end-of-file position after the read. If `offset` is past
    EOF (file rotated/truncated), reset to 0 and re-read from start.

    If `projected=True`, the JSONL stream is folded into a compact
    operator-readable form (drops streaming token deltas, thinking
    blocks, status heartbeats; collapses long tool_result bodies).
    The returned `offset` advances only past the last complete line so
    a partial JSON line at the chunk tail is retried on the next poll.

    If `structured=True`, returns {path, offset, events, eof} where
    `events` is a list of structured event dicts (see
    `_project_log_event`) suitable for a card-based renderer.
    """
    if not path or not os.path.exists(path):
        if structured:
            return {"path": path, "offset": 0, "events": [], "eof": 0}
        return {"path": path, "offset": 0, "content": "", "eof": 0}
    size = os.path.getsize(path)
    if offset > size:
        offset = 0
    end = min(size, offset + _TAIL_MAX_BYTES)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(end - offset)
    if not projected and not structured:
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
        if structured:
            return {"path": path, "offset": offset, "events": [], "eof": size}
        return {"path": path, "offset": offset, "content": "", "eof": size}
    complete = chunk[: last_nl + 1].decode("utf-8", errors="replace")
    new_offset = offset + last_nl + 1
    if structured:
        return {
            "path": path,
            "offset": new_offset,
            "events": _project_chunk_events(complete),
            "eof": size,
        }
    return {
        "path": path,
        "offset": new_offset,
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
    format: str = "text",
):
    """Tail the most recent phase agent log.

    If `slug` is given, tails that phase's most recent log. Otherwise
    auto-picks the most recently active slug (running > finished).
    Returns {slug, path, offset, content, eof} so the frontend can
    advance its local offset and detect log rotation.

    Defaults to a projected (filtered, human-readable) view of the
    JSONL agent log. Pass `projected=false` to get the raw JSONL.
    Pass `format=structured` to receive a list of structured event
    dicts under `events` (for card-based UIs).
    """
    target = slug or phase_runner.latest_active_slug()
    if target is None:
        if format == "structured":
            return {"slug": None, "path": None, "offset": 0, "events": [], "eof": 0}
        return {"slug": None, "path": None, "offset": 0, "content": "", "eof": 0}
    path = phase_runner.get_log_path(target)
    if format == "structured":
        out = _tail_file(path, offset, structured=True)
    else:
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
