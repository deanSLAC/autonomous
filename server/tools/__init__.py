"""Autonomous Beamline Agent tool system.

Merges the original BeamtimeHero read-only toolset with the autonomy
CAT-0..CAT-8 action surface.
"""

from tools.definitions import TOOL_DEFINITIONS as _BT_TOOLS, CLI_TOOL_DEFINITION
from tools.autonomy_definitions import (
    AUTONOMY_TOOL_DEFINITIONS,
    AUTONOMY_TOOL_CATEGORIES,
)
from tools.executor import execute_tool

TOOL_DEFINITIONS = _BT_TOOLS + AUTONOMY_TOOL_DEFINITIONS

__all__ = [
    "TOOL_DEFINITIONS",
    "CLI_TOOL_DEFINITION",
    "AUTONOMY_TOOL_DEFINITIONS",
    "AUTONOMY_TOOL_CATEGORIES",
    "execute_tool",
]
