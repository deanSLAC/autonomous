"""beamline_tools.spec_control — autonomy-side spec_cmd wrapper + upstream re-exports.

`spec_cmd` is the only autonomy-extended module here (it adds the
measure_beam_size plan_store write-through). Everything else
(`transport`, `phases`, transport clients) is re-exported from upstream
so existing `from beamline_tools.spec_control import X` imports keep
working without code change.
"""

from beamline_tools.spec_control import spec_cmd
from beamtimehero_cli.spec_control import (  # noqa: F401
    phases,
    sandbox_client,
    screen_client,
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
