"""beamline_tools.spec_control — SPEC dispatcher, allowlist, transports.

Layering:
  spec_cmd       — high-level command dispatcher (allowlist + transport router)
  transport      — DispatchResult, _MockScreen, busy-state (transport-agnostic)
  screen_client  — pure GNU-screen transport
  tcp_client     — pure TCP server-mode transport
  phase_allowlist — per-phase command/motor allowlist
"""

from beamline_tools.spec_control import (
    phase_allowlist,
    screen_client,
    spec_cmd,
    tcp_client,
    transport,
)

__all__ = [
    "phase_allowlist",
    "screen_client",
    "spec_cmd",
    "tcp_client",
    "transport",
]
