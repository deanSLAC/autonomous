"""Configuration for the ui package.

Owns: Slack IDs, FastAPI host/port/base path, static asset location,
experiment config YAML directory. Does not touch the LLM or the beamline
tools — it talks to orchestration.api for everything.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "ui" / "static"
CONFIG_DIR = PROJECT_ROOT / "config"
CONTEXT_DIR = PROJECT_ROOT / "context"

# ---------------------------------------------------------------------------
# Slack — secrets + channel IDs. Empty values disable the bridge.
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
SLACK_LLM_CHANNEL_ID = os.getenv("SLACK_LLM_CHANNEL_ID", "")
SLACK_USERS_CHANNEL_ID = os.getenv("SLACK_USERS_CHANNEL_ID", "")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
# Port 5005 — deliberately not 5000 (AirPlay on macOS) nor 8080 (everything else).
PORT = 5005
BASE_PATH = ""
