#!/usr/bin/env python
"""Smoke test for orchestration.agents lifecycle.

Spawns trivial bash subprocesses (NOT claude) to exercise the
spawn → drain → complete_run path and the kill → killpg path without
needing a working LLM gateway.

Run:
    SPEC_MOCK=1 venv/bin/python scripts/smoke_test_agents.py
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

# Ensure SPEC_MOCK so any indirect spec_cmd imports stay sandboxed.
os.environ.setdefault("SPEC_MOCK", "1")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from orchestration.agents import (  # noqa: E402
    get_run,
    kill,
    list_active,
    purge_orphans_at_startup,
    spawn,
)


def _make_launcher(body: str) -> Path:
    """Write a temp .sh that just runs `body`. The agents.spawn helper
    pipes stream-json into stdin which our trivial bash will simply
    discard — we only care about the registry lifecycle here."""
    tmp = tempfile.NamedTemporaryFile(
        prefix="agent_smoke_", suffix=".sh", delete=False, mode="w",
    )
    tmp.write(f"#!/usr/bin/env bash\n# discard stdin so the pipe doesn't block writers\ncat > /dev/null &\n{body}\nwait\n")
    tmp.flush()
    tmp.close()
    p = Path(tmp.name)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def test_spawn_completion() -> str:
    """Spawn `echo hi; sleep 1; echo done`, wait for completion, assert completed_at set."""
    print("\n[1/3] spawn → drain → complete_run lifecycle")
    script = _make_launcher("echo hi\nsleep 1\necho done")
    try:
        run_id = spawn(
            agent_type="control",
            task_text="smoke: hi/done",
            spawned_by="smoke-test",
            script_path=script,
            seed_prompt="ignored seed",
        )
        print(f"  spawned run_id={run_id}")
        # Poll up to 10s for completion.
        deadline = time.time() + 10.0
        row = None
        while time.time() < deadline:
            row = get_run(run_id)
            if row and row.get("completed_at"):
                break
            time.sleep(0.1)
        assert row is not None, "row vanished"
        assert row["completed_at"], f"completed_at not set: {row}"
        assert not row["killed"], f"unexpectedly marked killed: {row}"
        print(f"  completed_at={row['completed_at']} killed={row['killed']}")
        print(f"  result tail: {(row.get('result') or '')[-80:]!r}")
        return run_id
    finally:
        script.unlink(missing_ok=True)


def test_kill() -> str:
    """Spawn `sleep 60`; kill it; confirm it dies within seconds."""
    print("\n[2/3] kill → killpg path")
    script = _make_launcher("sleep 60")
    try:
        run_id = spawn(
            agent_type="control",
            task_text="smoke: long sleep",
            spawned_by="smoke-test",
            script_path=script,
            seed_prompt="ignored seed",
        )
        print(f"  spawned run_id={run_id}")
        # Give Popen a moment to actually fork the child.
        time.sleep(0.3)
        pre = get_run(run_id)
        pid = pre["pid"] if pre else None
        print(f"  pre-kill pid={pid} pgid={pre and pre['pgid']}")
        ok = kill(run_id, reason="smoke")
        print(f"  kill() returned {ok}")
        # /proc/<pid> should disappear quickly.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if pid is None:
                break
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.1)
        proc_alive = pid is not None and Path(f"/proc/{pid}").exists()
        assert not proc_alive, f"pid {pid} still alive after kill()"
        row = get_run(run_id)
        assert row is not None
        assert row["completed_at"], f"completed_at not set: {row}"
        assert row["killed"], f"killed flag not set: {row}"
        assert row["kill_reason"] == "smoke", f"kill_reason mismatch: {row}"
        print(f"  proc_alive={proc_alive} killed={row['killed']} reason={row['kill_reason']}")
        return run_id
    finally:
        script.unlink(missing_ok=True)


def test_list_active_empty() -> None:
    """After both tests, list_active() should be empty for our smoke runs."""
    print("\n[3/3] list_active sanity")
    active = list_active()
    print(f"  active rows: {len(active)}")
    # We can't assert ==0 strictly (the user may have other agents),
    # but our smoke runs should be gone.
    smoke_left = [r for r in active if r["spawned_by"] == "smoke-test"]
    assert not smoke_left, f"smoke runs still active: {smoke_left}"
    print("  no smoke-test rows in active set")


def main() -> int:
    print("orchestration.agents smoke test starting…")
    print(f"  PROJECT_ROOT={PROJECT_ROOT}")
    print(f"  SPEC_MOCK={os.environ.get('SPEC_MOCK')}")

    # Reap anything from a prior failed smoke run so we start clean.
    n = purge_orphans_at_startup()
    if n:
        print(f"  purge_orphans_at_startup: reaped {n} stale row(s)")

    test_spawn_completion()
    test_kill()
    test_list_active_empty()

    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
