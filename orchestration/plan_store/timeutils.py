"""Timezone-handling helpers for the plan_store layer.

The codebase's prevailing convention is naive local datetimes: every
`datetime.now()` and every SQLModel `default_factory=datetime.now` produces
a naive value in the host machine's local time, and SQLite columns are
declared without `timezone=True`. ISO strings entering the system (e.g.
from agents running `date -Iseconds`) often carry a tz offset, which mixes
poorly with that convention — parsing them with `datetime.fromisoformat`
yields a tz-aware datetime whose subtraction against a naive `now()`
silently produces wrong deltas (off by the local↔UTC offset).

`parse_iso_to_local_naive` is the single boundary helper that takes any
ISO-8601 input and returns a naive local datetime, so downstream storage
and arithmetic stay consistent.
"""

from datetime import datetime


def parse_iso_to_local_naive(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt
