"""Subprocess management for agent runs.

`spawn()` is sync (the orchestrator state machine drives it from sync
contexts) and returns the run_id immediately after Popen + DB insert.
A daemon thread drains stdout in the background, parses claude code's
stream-json events using the same `_ingest_event` / `_Accumulator` from
`orchestration.agent.claude_code_client`, and on `proc.wait()` calls
`runs.complete_run(run_id, result=final_text)`.

`kill()` does SIGTERM-then-SIGKILL on the process group (start_new_session=True
gives every spawn its own pgid == pid). `purge_orphans_at_startup()` is
the FastAPI lifespan hook that reaps anything still flagged active in
the DB from a previous server crash. `kill_all_at_shutdown()` is the
mirror image — graceful termination of every active row before the
server exits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from orchestration.agent.claude_code_client import _Accumulator, _ingest_event
from orchestration.agents import runs as agent_runs
from orchestration.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


def _stream_json_user_msg(text: str) -> str:
    """Wrap a user prompt in claude code's stream-json input shape.

    Mirrors `ClaudeCodeClient._stream_json_user_msg` — duplicated here so
    we don't need to instantiate that class just for one helper.
    """
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }) + "\n"


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------

def spawn(
    *,
    agent_type: str,
    task_text: str,
    spawned_by: str,
    script_path: Path,
    seed_prompt: str,
    experiment_id: Optional[str] = None,
    working_dir: Optional[Path] = None,
    claude_session_id: Optional[str] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> str:
    """Launch a Claude Code agent subprocess and register it.

    Returns the AgentRun.id immediately. A background daemon thread
    drains stdout, captures the final assistant text, and calls
    `complete_run()` when the subprocess exits.

    The subprocess is started with `start_new_session=True`, so the
    child gets its own session/process-group with `pgid == pid`. This
    lets `kill()` use `os.killpg(pgid, ...)` to reap the entire tree.
    """
    cwd = Path(working_dir) if working_dir else PROJECT_ROOT

    # 1. Insert the registry row first so we have an ID to thread into env.
    row = agent_runs.create_run(
        agent_type=agent_type,
        task_text=task_text,
        spawned_by=spawned_by,
        experiment_id=experiment_id,
        claude_session_id=claude_session_id,
        working_dir=str(cwd),
        script_path=str(script_path),
    )
    run_id = row.id

    # 2. Build env. The launcher .sh reads BEAMTIMEHERO_CLAUDE_SESSION_ID
    #    to decide between --resume and --session-id; the agent itself can
    #    read BEAMTIMEHERO_AGENT_RUN_ID to call back into the registry.
    env = {
        **os.environ,
        **(extra_env or {}),
        "BEAMTIMEHERO_AGENT_RUN_ID": run_id,
        "BEAMTIMEHERO_CLAUDE_SESSION_ID": claude_session_id or "",
    }

    # 3. Popen. start_new_session=True so we can killpg later.
    proc = subprocess.Popen(
        [str(script_path)],
        start_new_session=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=True,
        bufsize=1,
    )

    pid = proc.pid
    # With start_new_session=True the child becomes its own pg leader, so
    # pgid == pid. We avoid calling os.getpgid() (which can race if the
    # child has already exited) and trust the kernel guarantee.
    pgid = pid
    agent_runs.set_pid(run_id, pid=pid, pgid=pgid)

    # 4. Feed the seed prompt and close stdin. claude -p reads stream-json
    #    until stdin closes, then drives the agent loop on its own.
    try:
        if proc.stdin is not None:
            proc.stdin.write(_stream_json_user_msg(seed_prompt))
            proc.stdin.flush()
            proc.stdin.close()
    except (BrokenPipeError, OSError) as e:
        logger.warning("agent %s: stdin write failed: %s", run_id, e)

    # 5. Daemon thread drains stdout and finalizes the row on exit.
    threading.Thread(
        target=_drain_and_finalize,
        args=(run_id, proc),
        daemon=True,
        name=f"agent-drain-{run_id}",
    ).start()

    logger.info(
        "agent spawned: run_id=%s type=%s pid=%d script=%s",
        run_id, agent_type, pid, script_path,
    )
    return run_id


def _drain_and_finalize(run_id: str, proc: subprocess.Popen) -> None:
    """Background thread: read stdout, parse stream-json, complete the run on exit.

    Drains stdout to avoid Popen pipe-buffer deadlock. Parsing failures
    fall back gracefully — a non-JSON line is logged and skipped, and a
    crash mid-stream still lets us mark the row complete with whatever
    text we'd accumulated so far.
    """
    acc = _Accumulator()
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("agent %s: non-JSON line: %s", run_id, line[:200])
                    continue
                try:
                    _ingest_event(acc, event)
                    # If we just learned the session id and the row didn't
                    # have one, persist it so future --resume works.
                    if acc.session_id:
                        agent_runs.set_claude_session_id(run_id, acc.session_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("agent %s: ingest failed: %s", run_id, e)
    except Exception as e:  # noqa: BLE001
        logger.warning("agent %s: stdout drain raised: %s", run_id, e)

    rc = proc.wait()

    # Best-effort capture of stderr tail for diagnostics.
    stderr_tail = ""
    try:
        if proc.stderr is not None:
            stderr_tail = proc.stderr.read() or ""
    except Exception:  # noqa: BLE001
        stderr_tail = ""

    final_text = acc.final_text or "\n".join(acc.assistant_chunks).strip()
    if rc != 0 and not final_text:
        final_text = f"agent exited rc={rc}: {stderr_tail[:300]}"
    elif rc != 0:
        logger.warning("agent %s: exited rc=%d (stderr tail: %s)",
                       run_id, rc, stderr_tail[:300])

    # If the row was already marked killed via kill(), don't clobber that.
    existing = agent_runs.get_run(run_id)
    if existing and existing.get("completed_at"):
        return
    agent_runs.complete_run(run_id, result=final_text)
    logger.info("agent %s: completed (rc=%d, %d chars)",
                run_id, rc, len(final_text or ""))


# ---------------------------------------------------------------------------
# kill
# ---------------------------------------------------------------------------

def kill(run_id: str, *, reason: str = "manual") -> bool:
    """Terminate the subprocess group for this run.

    SIGTERM, wait up to 5 s, then SIGKILL. Returns True if we issued any
    signal at all, False if the run was already completed (no-op).

    The drain thread will still call complete_run(result=...) on its own
    once `proc.wait()` returns, but it short-circuits if the row already
    has completed_at set — which we set here. Order matters: mark the
    row killed BEFORE killpg so the drain thread doesn't write a
    "result" overtop of the kill_reason.
    """
    row = agent_runs.get_run(run_id)
    if row is None:
        logger.warning("kill(): unknown run_id %s", run_id)
        return False
    if row.get("completed_at"):
        return False
    pgid = row.get("pgid")
    if pgid is None:
        logger.warning("kill(): run %s has no pgid recorded", run_id)
        agent_runs.complete_run(run_id, killed=True, kill_reason=reason)
        return True

    # Mark the row first so the drain thread's post-wait complete_run
    # short-circuits.
    agent_runs.complete_run(run_id, killed=True, kill_reason=reason)

    # SIGTERM
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        # Already gone — nothing to do.
        return True
    except PermissionError as e:
        logger.warning("kill(): SIGTERM denied for pgid=%d: %s", pgid, e)
        return False

    # Wait up to 5 s for graceful exit.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            # Signal 0 = check existence without sending.
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)

    # Still alive — SIGKILL.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as e:
        logger.warning("kill(): SIGKILL denied for pgid=%d: %s", pgid, e)
    return True


# ---------------------------------------------------------------------------
# Startup orphan sweep
# ---------------------------------------------------------------------------

def _proc_cmdline(pid: int) -> str:
    """Read /proc/<pid>/cmdline. Empty string if process is gone."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
        # cmdline args are NUL-separated.
        return raw.replace(b"\0", b" ").decode("utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return ""


def _proc_owned_by_self(pid: int) -> bool:
    """True if /proc/<pid> is owned by our uid."""
    try:
        st = os.stat(f"/proc/{pid}")
        return st.st_uid == os.geteuid()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False


def purge_orphans_at_startup() -> int:
    """Reap rows that were active when the server last died.

    Strategy:
      - For every `agentrun` row with completed_at IS NULL:
        - If /proc/<pid>/cmdline contains 'claude' AND we own the pid,
          killpg it (SIGKILL, since it's already orphaned).
        - Mark complete_run(killed=True, kill_reason='orphan from previous session').

    Returns count of rows purged.
    """
    active = agent_runs.list_active()
    n = 0
    for row in active:
        run_id = row["id"]
        pid = row.get("pid")
        pgid = row.get("pgid")
        cmdline = _proc_cmdline(pid) if pid else ""
        if pid and pgid and "claude" in cmdline and _proc_owned_by_self(pid):
            try:
                os.killpg(pgid, signal.SIGKILL)
                logger.info("purge_orphans: killed pgid=%d (run %s)", pgid, run_id)
            except (ProcessLookupError, PermissionError) as e:
                logger.debug("purge_orphans: killpg(%d) raised %s", pgid, e)
        agent_runs.complete_run(
            run_id, killed=True, kill_reason="orphan from previous session"
        )
        n += 1
    if n:
        logger.info("purge_orphans_at_startup: reaped %d row(s)", n)
    return n


# ---------------------------------------------------------------------------
# Shutdown sweep
# ---------------------------------------------------------------------------

async def kill_all_at_shutdown() -> None:
    """Kill every still-active agent at FastAPI shutdown. Run concurrently."""
    active = agent_runs.list_active()
    if not active:
        return

    async def _one(run_id: str) -> bool:
        return await asyncio.to_thread(kill, run_id, reason="app shutdown")

    results = await asyncio.gather(
        *[_one(r["id"]) for r in active],
        return_exceptions=True,
    )
    killed = sum(1 for r in results if r is True)
    logger.info("kill_all_at_shutdown: terminated %d/%d agents", killed, len(active))
