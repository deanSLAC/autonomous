"""Autonomy-side re-export of upstream's audited dispatch wrapper.

Upstream `beamtimehero_cli.audited_call` reads phase + experiment_id from
`beamtimehero_cli.runtime_state`. Autonomy's `orchestration.runtime_state`
is the canonical writer (it owns the plan_store DB write-through); it
mirrors every update to the upstream runtime_state, so upstream's
`audited_call` reads the right state without modification.

This file exists so existing consumers can keep
`from beamline_tools.audited_call import audited_call` unchanged.
"""

from __future__ import annotations

from beamtimehero_cli.audited_call import audited_call

__all__ = ["audited_call"]
