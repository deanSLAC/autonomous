"""Steering CLI surface.

Bespoke `beamtimehero steering ...` subtree that lets a running control
agent walk the StaffGuidance steering queue: list pending rows, ack them,
attach an ack comment, complete them with a result, or defer.

The leaf commands are wired in by `scripts/beamtimehero` (see
`_run_steering`); this package only owns the per-leaf functions.
"""

from beamline_tools.steering import cli

__all__ = ["cli"]
