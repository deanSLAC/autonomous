"""Initialize the orchestration + action_log SQLite databases.

After the three-package split there are two sqlite files:

  * `beamline_tools.db` — action_log, query_log
  * `orchestration.db`  — experiment, plan, phase_run, staff_guidance, ...

Both schemas are created here (idempotent) by delegating to each
package's own `init_db()`. Any pending additive column migrations on
the orchestration side run at the same time.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect, text

from orchestration.plan_store import models  # noqa: F401 — register tables
from orchestration.plan_store.session import get_engine as get_orch_engine


# Columns added since the original schema. Keep additive only.
_PENDING_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "experiment": [
        ("spectrometer_aligned", "INTEGER NOT NULL DEFAULT 0"),
        ("beam_h_fwhm_um", "REAL"),
        ("beam_v_fwhm_um", "REAL"),
        ("calibration_foil_element", "TEXT"),
        ("calibration_foil_detector", 'TEXT NOT NULL DEFAULT "I2"'),
        ("end_time", "TIMESTAMP"),
    ],
    "collectionscan": [
        ("spot_index", "INTEGER"),
    ],
    "experimentelement": [
        ("measurement_mode", 'TEXT NOT NULL DEFAULT "XES"'),
        ("emission_line", "TEXT"),
        ("vortex_counter", "TEXT"),
    ],
    "sampleposition": [
        ("i0_gain", "TEXT"),
        ("i0_offset", "TEXT"),
        ("i1_gain", "TEXT"),
        ("survey_counts_per_sec", "REAL"),
        ("survey_energy_ev", "REAL"),
        ("survey_completed_at", "TIMESTAMP"),
        ("survey_notes", "TEXT"),
    ],
    "sampleholder": [
        ("queue_order", "INTEGER NOT NULL DEFAULT 0"),
        ("notes", "TEXT"),
    ],
    # Steering-queue state-machine columns. New in the orchestrator
    # decoupling refactor — see plan_store/models.py:StaffGuidance.
    "staffguidance": [
        ("orchestrator_ack_at", "TIMESTAMP"),
        ("ack_comment", "TEXT"),
        ("active_agent_run_id", "TEXT"),
        ("active_agent_ack_at", "TIMESTAMP"),
        ("completed_at", "TIMESTAMP"),
        ("result", "TEXT"),
        ("slack_channel", "TEXT"),
        ("slack_thread_ts", "TEXT"),
        ("is_stop", "BOOLEAN NOT NULL DEFAULT 0"),
        ("slack_replied_at", "TIMESTAMP"),
        ("target_agent_type", "TEXT"),
    ],
}

_ACTION_LOG_PENDING_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "actionlog": [
        ("invalidated_at", "TIMESTAMP"),
    ],
}


def _apply_column_migrations(engine, pending: dict[str, list[tuple[str, str]]]) -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in pending.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            for col_name, col_def in cols:
                if col_name in existing_cols:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_def}'))
                print(f"  migrated: {table}.{col_name} added")


def _backfill_vortex_counter(engine) -> None:
    """One-time backfill of experimentelement.vortex_counter from the
    legacy vortex_channel int (1 → 'vortDT', 3 → 'vortDT2'). Rows whose
    vortex_counter has already been set are left alone.
    """
    insp = inspect(engine)
    if "experimentelement" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("experimentelement")}
    if "vortex_counter" not in cols or "vortex_channel" not in cols:
        return
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE experimentelement SET vortex_counter = "
            "CASE vortex_channel "
            "WHEN 1 THEN 'vortDT' "
            "WHEN 3 THEN 'vortDT2' "
            "WHEN 5 THEN 'vortDT3' "
            "WHEN 7 THEN 'vortDT4' "
            "ELSE 'vortDT' END "
            "WHERE vortex_counter IS NULL OR vortex_counter = ''"
        ))
        if result.rowcount:
            print(f"  backfilled: experimentelement.vortex_counter on {result.rowcount} rows")


def init_db() -> None:
    """Create tables for both beamline_tools and orchestration DBs."""
    from beamline_tools.action_log.session import get_engine as get_tools_engine

    orch_engine = get_orch_engine()
    _apply_column_migrations(orch_engine, _PENDING_COLUMNS)
    _backfill_vortex_counter(orch_engine)
    print(f"orchestration DB initialized: {os.environ.get('ORCHESTRATION_DB_PATH')}")

    tools_engine = get_tools_engine()
    _apply_column_migrations(tools_engine, _ACTION_LOG_PENDING_COLUMNS)
    print(f"beamline_tools DB initialized: {os.environ.get('BEAMLINE_TOOLS_DB_PATH')}")


if __name__ == "__main__":
    init_db()
