"""beamline_tools.spec_control — SPEC dispatcher, phase vocab, transports.

Layering:
  spec_cmd        — high-level command dispatcher (transport router)
  transport       — DispatchResult, _MockScreen, busy-state (transport-agnostic)
  sandbox_client  — spec-eval Docker API transport
  screen_client   — pure GNU-screen transport
  tcp_client      — pure TCP server-mode transport
  phases          — phase constants + agent-role motor/spec-write allowlists
"""

from beamline_tools.spec_control import (
    phases,
    sandbox_client,
    screen_client,
    spec_cmd,
    tcp_client,
    transport,
)

__all__ = [
    "phases",
    "sandbox_client",
    "screen_client",
    "spec_cmd",
    "tcp_client",
    "transport",
]
