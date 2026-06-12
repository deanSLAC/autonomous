"""ScanRecord capture from the tool-executor hook (beamline_tools/scan_capture).

A scan-emitting action tool returns {"ok": true, "action_id": ...}; when
the agent runs under a phase tile (BEAMTIMEHERO_PHASE_RUN_ID set) the
capture hook must read the action-log row's scan_number and insert a
ScanRecord keyed to that phase run — and do nothing in every other case.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools import scan_capture  # noqa: E402
from beamtimehero_cli.action_log import session as action_session_mod  # noqa: E402
from beamtimehero_cli.action_log.models import ActionLog  # noqa: E402
from orchestration.plan_store import session as plan_session_mod  # noqa: E402
from orchestration.plan_store.models import ScanRecord  # noqa: E402


@pytest.fixture
def dbs(monkeypatch, tmp_path):
    """Two throwaway sqlite files standing in for the real DBs."""
    action_engine = create_engine(f"sqlite:///{tmp_path}/action.db")
    plan_engine = create_engine(f"sqlite:///{tmp_path}/plan.db")
    ActionLog.metadata.create_all(action_engine)
    SQLModel.metadata.create_all(plan_engine)

    @contextmanager
    def action_session():
        with Session(action_engine) as s:
            yield s

    @contextmanager
    def plan_session():
        with Session(plan_engine) as s:
            yield s

    monkeypatch.setattr(action_session_mod, "get_session", action_session)
    monkeypatch.setattr(plan_session_mod, "get_session", plan_session)
    return {"action": action_engine, "plan": plan_engine}


def _add_action(engine, *, scan_number, command="ascan",
                args=("m1vert", "1.7", "2.1", "41", "0.5")):
    row = ActionLog(
        phase="beamline_alignment",
        command=command,
        args_json=json.dumps(list(args)),
        spec_string_sent=f"{command} " + " ".join(args),
        justification="test",
        scan_number=scan_number,
    )
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def _scan_records(engine):
    with Session(engine) as s:
        return list(s.exec(select(ScanRecord)))


def _result(action_id):
    return json.dumps({"ok": True, "kind": "action", "action_id": action_id})


def test_scan_action_inserts_record(dbs, monkeypatch):
    monkeypatch.setenv("BEAMTIMEHERO_PHASE_RUN_ID", "pr-1")
    row = _add_action(dbs["action"], scan_number=42)
    scan_capture.capture_scan_record("run_motor_scan", _result(row.id))

    records = _scan_records(dbs["plan"])
    assert len(records) == 1
    rec = records[0]
    assert rec.phase_run_id == "pr-1"
    assert rec.scan_number == 42
    assert rec.motor_name == "m1vert"
    assert rec.scan_type == "ascan"
    # Provenance stamped back onto the action row.
    with Session(dbs["action"]) as s:
        assert s.get(ActionLog, row.id).phase_run_id == "pr-1"


def test_implied_motor_for_run_xas(dbs, monkeypatch):
    monkeypatch.setenv("BEAMTIMEHERO_PHASE_RUN_ID", "pr-2")
    row = _add_action(dbs["action"], scan_number=7, command="run_xas",
                      args=("0.5", "1"))
    scan_capture.capture_scan_record("run_xas", _result(row.id))
    assert _scan_records(dbs["plan"])[0].motor_name == "energy"


def test_non_scan_action_is_skipped(dbs, monkeypatch):
    monkeypatch.setenv("BEAMTIMEHERO_PHASE_RUN_ID", "pr-3")
    row = _add_action(dbs["action"], scan_number=None, command="umv",
                      args=("Sx", "1.0"))
    scan_capture.capture_scan_record("move_motor", _result(row.id))
    assert _scan_records(dbs["plan"]) == []


def test_no_phase_run_env_is_a_no_op(dbs, monkeypatch):
    monkeypatch.delenv("BEAMTIMEHERO_PHASE_RUN_ID", raising=False)
    row = _add_action(dbs["action"], scan_number=42)
    scan_capture.capture_scan_record("run_motor_scan", _result(row.id))
    assert _scan_records(dbs["plan"]) == []


def test_non_json_and_error_results_are_no_ops(dbs, monkeypatch):
    monkeypatch.setenv("BEAMTIMEHERO_PHASE_RUN_ID", "pr-4")
    scan_capture.capture_scan_record("read_scan", "not json")
    scan_capture.capture_scan_record(
        "run_motor_scan", json.dumps({"ok": False, "action_id": "a-1"}),
    )
    assert _scan_records(dbs["plan"]) == []
