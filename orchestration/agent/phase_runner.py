"""Per-phase agent process manager.

The dashboard spawns one Claude-CLI subprocess per phase tile (beamline
alignment / sample alignment / sample survey / data collection /
planner). Each tile maps to a shell script under scripts/ that wraps
`claude -p` with the right system prompt + tool allowlist.

This module:

  * Tracks the running subprocess per phase slug ({slug: Popen}).
  * Tees the script's combined stdout/stderr to logs/phase_<slug>_<ts>.log.
  * Records an `AgentRun` row (agent_type=slug) for every spawn so
    steering re-dispatch and orphan sweeps see phase agents the same
    way they see chat agents. The `BEAMTIMEHERO_AGENT_RUN_ID` env var
    is set so any `beamtimehero steering ack` issued by the agent
    auto-links back to its row.
  * Cleans up the slot + completes the AgentRun row when the process
    exits (a small daemon thread waits on each Popen).

Public API:

  start(slug, *, seed_text=None)
                       → spawn or fail with ValueError("already running")
  kill(slug)           → SIGTERM + clean up
  status_all()         → {slug: {state, pid, log_path, exit_code, run_id}}
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from orchestration.agents import runs as agent_runs
from orchestration.agents.spawn import _stream_json_user_msg
from orchestration.plan_store.session import (
    create_phase_run,
    complete_phase_run,
)

logger = logging.getLogger(__name__)


PHASE_SCRIPTS: dict[str, str] = {
    "beamline_alignment": "scripts/bl-aligner-claude.sh",
    "sample_alignment": "scripts/sample-aligner-claude.sh",
    "sample_survey": "scripts/sample-surveyor-claude.sh",
    "collection": "scripts/data-collection-claude.sh",
    "planner": "scripts/planner-claude.sh",
}


_PHASE_LABELS: dict[str, str] = {
    "beamline_alignment": "beamline alignment",
    "sample_alignment": "sample alignment",
    "sample_survey": "sample survey",
    "collection": "data collection",
    "planner": "planner",
}


def _default_seed(slug: str) -> str:
    label = _PHASE_LABELS.get(slug, slug.replace("_", " "))
    if slug == "collection":
        return (
            f"Begin the {label} phase. Follow the procedure in your system "
            "prompt end-to-end. You run until manually interrupted — do not "
            "exit on your own. When the queue is exhausted, loop back and "
            "keep collecting."
        )
    return (
        f"Begin the {label} phase. Follow the procedure in your system "
        "prompt end-to-end and finish with the success / blocked / halt "
        "shape from the base contract."
    )


@dataclass
class _Slot:
    proc: subprocess.Popen
    log_path: str
    log_file: object  # file handle
    started_at: float
    run_id: str
    phase_run_id: Optional[str] = None
    exit_code: Optional[int] = None
    finished_at: Optional[float] = None


_lock = threading.Lock()
_slots: dict[str, _Slot] = {}
# Last-known result per slug so the UI can render "complete"/"failed" tiles
# after a process exits.
_last_results: dict[str, dict] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _logs_dir() -> Path:
    p = _project_root() / "logs"
    p.mkdir(exist_ok=True)
    return p


# Per-field cap for JSONL records written by the child agent. Whole-line
# pass-through threshold sits a bit above this so small lines never pay
# the JSON parse cost. The matching consumer-side cap (`_TAIL_MAX_BYTES`)
# in ui/server/routers/phase_runner_api.py is 64 KB; truncating at 32 KB
# per field keeps post-parse re-serialized lines comfortably below it.
_JSONL_MAX_FIELD_BYTES = 32 * 1024
_LINE_PASSTHROUGH_BYTES = 48 * 1024


def _truncate_large_strings(obj, max_bytes: int):
    """Walk a parsed-JSON structure and replace any string value longer than
    `max_bytes` with a `<TRUNCATED N bytes>` marker. Mutates dicts/lists
    in-place where possible; returns the (possibly-replaced) value.
    """
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            obj[k] = _truncate_large_strings(obj[k], max_bytes)
        return obj
    if isinstance(obj, list):
        return [_truncate_large_strings(x, max_bytes) for x in obj]
    if isinstance(obj, str) and len(obj) > max_bytes:
        return f"<TRUNCATED {len(obj)} bytes>"
    return obj


def _truncate_jsonl_line(line: bytes) -> bytes:
    """Pass small lines through unchanged; for oversized lines parse JSON
    and truncate any string field that exceeds `_JSONL_MAX_FIELD_BYTES`.

    The dominant source of oversized lines is matplotlib PNG base64 in
    `tool_result.content[].image.source.data`; the recursive walk catches
    them regardless of position. Falls back to raw passthrough if the
    line isn't valid JSON (e.g. stderr noise merged via STDERR=STDOUT).
    """
    if len(line) <= _LINE_PASSTHROUGH_BYTES:
        return line
    stripped = line.rstrip(b"\r\n")
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return line
    truncated = _truncate_large_strings(obj, _JSONL_MAX_FIELD_BYTES)
    return (json.dumps(truncated) + "\n").encode("utf-8")


def _pump_log(proc: subprocess.Popen, log_file) -> None:
    """Stream the child's merged stdout/stderr to `log_file`, applying
    per-field JSONL truncation to oversized lines. Owns `log_file`
    lifecycle — closes it on EOF.
    """
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, b""):
            try:
                log_file.write(_truncate_jsonl_line(line))
            except Exception as e:  # noqa: BLE001
                # On unexpected truncation failure fall back to raw write
                # so we never lose log content.
                try:
                    log_file.write(line)
                except Exception:
                    pass
                logger.warning("phase_runner: log-pump truncation error: %s", e)
    finally:
        try:
            log_file.flush()
            log_file.close()
        except Exception:
            pass


def _watch_exit(slug: str, slot: _Slot) -> None:
    rc = slot.proc.wait()
    slot.exit_code = rc
    slot.finished_at = time.time()
    # log_file is owned by the _pump_log thread, which closes it on EOF
    # after draining proc.stdout. Nothing to do here.
    # Mark the AgentRun row complete unless kill() already did.
    try:
        existing = agent_runs.get_run(slot.run_id)
        if existing and not existing.get("completed_at"):
            agent_runs.complete_run(
                slot.run_id,
                result=f"phase agent exited rc={rc} log={slot.log_path}",
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_runner: complete_run failed for %s: %s", slot.run_id, e)
    # Mark the matching PhaseRun (if any) complete/failed. kill() sets
    # status="aborted" before us, so only update if still running. On
    # successful exit we also render the phase summary image (best
    # effort) and stamp its path onto the row so the dashboard / Slack
    # surface it.
    if slot.phase_run_id:
        try:
            from orchestration.plan_store.session import get_phase_run
            existing_pr = get_phase_run(slot.phase_run_id)
            if existing_pr and existing_pr.status == "running":
                summary_image_path: Optional[str] = None
                if rc == 0:
                    try:
                        from orchestration.agent import phase_reports
                        summary_image_path = phase_reports.generate_and_post(
                            slug, slot.phase_run_id,
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "phase_runner: phase_reports.generate_and_post failed for %s: %s",
                            slot.phase_run_id, e,
                        )
                complete_phase_run(
                    slot.phase_run_id,
                    status="completed" if rc == 0 else "failed",
                    summary_image_path=summary_image_path,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("phase_runner: complete_phase_run failed for %s: %s",
                           slot.phase_run_id, e)
    elif rc == 0:
        # No PhaseRun row → no phase summary render, no Slack post. This
        # is what happens when experiment_id wasn't set at spawn time.
        # Log loudly so the silent failure mode doesn't recur unnoticed.
        logger.warning(
            "phase_runner: %s exited rc=0 but had no phase_run_id; "
            "skipping summary render + Slack post (was experiment_id set?)",
            slug,
        )
    with _lock:
        _last_results[slug] = {
            "exit_code": rc,
            "log_path": slot.log_path,
            "started_at": slot.started_at,
            "finished_at": slot.finished_at,
            "run_id": slot.run_id,
        }
        # Only clear the slot if it still points at this proc (avoid
        # racing a fresh start that re-used the slug).
        cur = _slots.get(slug)
        if cur is slot:
            _slots.pop(slug, None)
    logger.info("phase agent %s exited rc=%s log=%s", slug, rc, slot.log_path)


def start(slug: str, *, seed_text: Optional[str] = None,
          spawned_by: str = "ui:phase-tile") -> dict:
    """Spawn the phase agent script for `slug`. Returns a status dict.

    Raises ValueError if already running, or if the slug/script is unknown.

    `seed_text` is the kickoff user message delivered to claude over
    stdin (the launcher uses `--input-format stream-json`). The
    orchestrator tick uses it to inject focused-task seeds for steering
    re-dispatch ("you were spawned to handle just steering id <X>"). It
    is also recorded as `task_text` on the AgentRun row. When no seed
    is provided (the dashboard "Run" button), `_default_seed(slug)`
    supplies a generic kickoff so the agent has a user turn to act on.
    """
    if slug not in PHASE_SCRIPTS:
        raise ValueError(f"unknown phase slug: {slug!r}")
    script = _project_root() / PHASE_SCRIPTS[slug]
    if not script.exists():
        raise ValueError(f"script missing: {script}")

    # Pull experiment_id from spec_cmd if available so the row is correctly
    # scoped. Lazy import — phase_runner is loaded at orchestration startup
    # before spec_cmd is wired in some test contexts.
    try:
        from orchestration import runtime_state
        experiment_id = runtime_state.get_experiment_id()
    except Exception:  # noqa: BLE001
        experiment_id = None

    kickoff = seed_text or _default_seed(slug)

    with _lock:
        # One phase agent at a time among the SPEC-touching phase tiles.
        # The planner runs continuously alongside whichever phase agent
        # is active (it reads plan_store + nudges the queue, never sends
        # SPEC commands), so it is excluded from this mutual-exclusion
        # check on both sides: starting the planner doesn't care what
        # else is running, and starting another phase doesn't care if
        # the planner is up.
        if slug != "planner":
            for other_slug, other_slot in _slots.items():
                if other_slug == "planner":
                    continue
                if other_slot.proc.poll() is None:
                    if other_slug == slug:
                        raise ValueError(f"phase agent for {slug!r} already running")
                    raise ValueError(
                        f"another phase agent is already running ({other_slug!r}); "
                        f"kill it before starting {slug!r}"
                    )
        else:
            # Planner: only refuse if the planner itself is already up.
            existing = _slots.get("planner")
            if existing is not None and existing.proc.poll() is None:
                raise ValueError("phase agent for 'planner' already running")

        # Pre-create the AgentRun so we can pass run_id into env before Popen.
        row = agent_runs.create_run(
            agent_type=slug,
            task_text=kickoff,
            spawned_by=spawned_by,
            experiment_id=experiment_id,
            script_path=str(script),
            working_dir=str(_project_root()),
        )
        run_id = row.id

        # Pre-create the matching PhaseRun row so the dashboard tile has
        # something to render for this in-flight phase. PhaseRun
        # requires an experiment_id, so skip the row in test contexts
        # where spec_cmd has no experiment wired up.
        phase_run_id: Optional[str] = None
        if experiment_id:
            try:
                phase_run = create_phase_run(
                    experiment_id=experiment_id, phase=slug,
                )
                phase_run_id = phase_run.id
            except Exception as e:  # noqa: BLE001
                logger.warning("phase_runner: create_phase_run failed: %s", e)

        ts = time.strftime("%Y%m%d-%H%M%S")
        log_path = _logs_dir() / f"phase_{slug}_{ts}.log"
        log_file = open(log_path, "ab", buffering=0)
        env = {**os.environ, "BEAMTIMEHERO_AGENT_RUN_ID": run_id}
        # stdout=PIPE (not the raw log fd) so a pump thread can truncate
        # oversized JSONL records before they hit disk. The fast-path in
        # _truncate_jsonl_line keeps small-line overhead near zero.
        proc = subprocess.Popen(
            ["bash", str(script)],
            cwd=str(_project_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            env=env,
            start_new_session=True,  # so SIGTERM kills the whole subtree
        )
        # start_new_session=True → child becomes its own pg leader; pgid == pid.
        agent_runs.set_pid(run_id, pid=proc.pid, pgid=proc.pid)
        threading.Thread(
            target=_pump_log, args=(proc, log_file), daemon=True,
        ).start()
        # Feed the kickoff user message and close stdin. claude -p reads
        # stream-json until EOF, then drives the agent loop on its own.
        try:
            if proc.stdin is not None:
                proc.stdin.write(_stream_json_user_msg(kickoff).encode("utf-8"))
                proc.stdin.flush()
                proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            logger.warning("phase_runner: stdin write failed for %s: %s", slug, e)
        slot = _Slot(
            proc=proc,
            log_path=str(log_path),
            log_file=log_file,
            started_at=time.time(),
            run_id=run_id,
            phase_run_id=phase_run_id,
        )
        _slots[slug] = slot

    threading.Thread(
        target=_watch_exit, args=(slug, slot), daemon=True,
    ).start()

    return {
        "slug": slug,
        "pid": proc.pid,
        "run_id": run_id,
        "log_path": str(log_path),
        "started_at": slot.started_at,
    }


def kill(slug: str, *, reason: str = "manual") -> dict:
    """Send SIGTERM to the running phase agent. Returns status dict."""
    with _lock:
        slot = _slots.get(slug)
    if slot is None or slot.proc.poll() is not None:
        raise ValueError(f"no phase agent running for {slug!r}")

    # Mark the row killed first so the watcher's complete_run short-circuits.
    try:
        agent_runs.complete_run(slot.run_id, killed=True, kill_reason=reason)
    except Exception as e:  # noqa: BLE001
        logger.warning("phase_runner.kill: complete_run failed for %s: %s",
                       slot.run_id, e)
    if slot.phase_run_id:
        try:
            complete_phase_run(slot.phase_run_id, status="aborted",
                               notes=f"killed: {reason}")
        except Exception as e:  # noqa: BLE001
            logger.warning("phase_runner.kill: complete_phase_run failed for %s: %s",
                           slot.phase_run_id, e)
    try:
        # killpg because we set start_new_session=True
        os.killpg(slot.proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.warning("killpg failed for %s, falling back to terminate(): %s", slug, e)
        try:
            slot.proc.terminate()
        except Exception:
            pass
    return {"slug": slug, "killed": True, "pid": slot.proc.pid, "run_id": slot.run_id}


def kill_all() -> list[dict]:
    """SIGTERM every running phase agent. Returns one status dict per kill."""
    results: list[dict] = []
    with _lock:
        running = [
            slug for slug, slot in _slots.items()
            if slot.proc.poll() is None
        ]
    for slug in running:
        try:
            results.append(kill(slug))
        except ValueError:
            # Race: process exited between the snapshot and the kill call.
            pass
    return results


def status_all() -> dict:
    """Return {slug: {state, ...}} for every known phase."""
    out: dict[str, dict] = {}
    with _lock:
        for slug in PHASE_SCRIPTS:
            slot = _slots.get(slug)
            if slot is not None and slot.proc.poll() is None:
                out[slug] = {
                    "state": "running",
                    "pid": slot.proc.pid,
                    "run_id": slot.run_id,
                    "log_path": slot.log_path,
                    "started_at": slot.started_at,
                }
            else:
                last = _last_results.get(slug)
                if last is None:
                    out[slug] = {"state": "idle"}
                else:
                    rc = last.get("exit_code")
                    state = "complete" if rc == 0 else "failed"
                    out[slug] = {
                        "state": state,
                        "exit_code": rc,
                        "run_id": last.get("run_id"),
                        "log_path": last.get("log_path"),
                        "started_at": last.get("started_at"),
                        "finished_at": last.get("finished_at"),
                    }
    return out


def is_running(slug: str) -> bool:
    """True if a phase agent for `slug` is currently running."""
    with _lock:
        slot = _slots.get(slug)
        return slot is not None and slot.proc.poll() is None


def get_log_path(slug: str) -> Optional[str]:
    """Return the most recent log path for a slug (running or finished)."""
    with _lock:
        slot = _slots.get(slug)
        if slot is not None:
            return slot.log_path
        last = _last_results.get(slug)
        return last.get("log_path") if last else None


def latest_active_slug(exclude: Optional[Iterable[str]] = None) -> Optional[str]:
    """Pick the most recently started slug — running first, finished otherwise.

    Used by the dashboard's Agent Output panel to auto-tail whichever
    phase is currently active without the operator picking one.

    `exclude` is an optional iterable of slugs to skip — used by the
    Agent Output panel to ignore the planner (which has its own panel).
    """
    skip = set(exclude or ())
    with _lock:
        running = [
            (slot.started_at, slug)
            for slug, slot in _slots.items()
            if slug not in skip and slot.proc.poll() is None
        ]
        if running:
            running.sort(reverse=True)
            return running[0][1]
        finished = [
            (info.get("finished_at") or info.get("started_at") or 0, slug)
            for slug, info in _last_results.items()
            if slug not in skip
        ]
    if not finished:
        return None
    finished.sort(reverse=True)
    return finished[0][1]
