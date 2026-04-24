"""Entry point for the Autonomous Beamline Agent.

Run:
    uvicorn main:app --host 127.0.0.1 --port 5005
or (dev):
    python main.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Simulation bootstrap MUST run before bl_config is imported, because
# bl_config reads BL_SCAN_DIR / BL_LOGS_DIR at import time.
import simulation as _sim  # noqa: E402

_SIM_INFO = _sim.bootstrap()

# Importing `orchestration` triggers any orchestration-side tool
# registration (CAT-8 plan tools) into beamline_tools.tool_catalog so
# the full tool surface is visible to generate_opencode_tools and the
# in-process dispatch.
import orchestration  # noqa: F401, E402

from ui import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    import uvicorn

    from ui.config import PORT

    port = int(os.getenv("PORT", str(PORT)))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
