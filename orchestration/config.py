"""Configuration for the orchestration package.

.env is the single source of truth for every operator-editable value.
This module reads env vars via pydantic-settings — no code-level defaults
for anything that appears in .env.example.  If a required value is missing,
the app errors loudly at boot with the variable name.

Internal constants (paths, cadences, ports) that operators never touch
are plain Python attributes below.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Paths (derived from repo layout, not configurable)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load autonomous's .env into os.environ. pydantic_settings reads its own copy
# into the Settings model, but the model_validator below also consults
# `os.environ.get("SLAC_BASE_URL")` / `STANFORD_BASE_URL` directly — so the
# env vars need to be in the process environment, not just the model. Run
# this here (early in the orchestration import chain) so the load happens
# regardless of which beamline_tools / beamtimehero_cli paths run later.
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class LLMGatewayName(str, Enum):
    slac = "slac"
    stanford = "stanford"
    default = "default"


# ---------------------------------------------------------------------------
# Gateway block — one per upstream provider
# ---------------------------------------------------------------------------
def _gateway_extra_env(prefix: str) -> dict[str, str]:
    """Collect arbitrary additional <PREFIX>* env vars (everything except
    the three the Settings model declares) for pass-through to the agent
    subprocess environment."""
    skip = {"BASE_URL", "API_KEY", "MODEL_ALIAS"}
    return {
        k.removeprefix(prefix): v
        for k, v in os.environ.items()
        if k.startswith(prefix) and k.removeprefix(prefix) not in skip
    }


_DEFAULT_GATEWAY = {"url": None, "key": "", "model_alias": None, "env": {}}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- operator-editable (must be in .env, no code-level defaults) -------
    LLM_GATEWAY: LLMGatewayName
    CLAUDE_MODEL: str = ""
    SLAC_API_KEY: str = ""
    SLAC_BASE_URL: str = ""
    SLAC_MODEL_ALIAS: str = ""
    STANFORD_API_KEY: str = ""
    STANFORD_BASE_URL: str = ""
    STANFORD_MODEL_ALIAS: str = ""

    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    SLACK_STEERING_CHANNEL_ID: str = ""
    SLACK_CHAT_CHANNEL_ID: str = ""

    SPEC_MOCK: str = ""
    BL_SCAN_DIR: str = ""
    BL_LOGS_DIR: str = ""

    MLFLOW_ENABLED: bool = False
    MLFLOW_TRACKING_URI: str = ""
    MLFLOW_TRACKING_TOKEN: str = ""

    @model_validator(mode="after")
    def _validate_gateway_credentials(self) -> "Settings":
        if self.LLM_GATEWAY == LLMGatewayName.slac:
            if not self.SLAC_API_KEY:
                raise ValueError(
                    "LLM_GATEWAY=slac requires SLAC_API_KEY to be set in .env"
                )
            if not self.SLAC_BASE_URL:
                raise ValueError(
                    "LLM_GATEWAY=slac requires SLAC_BASE_URL to be set in .env"
                )
        elif self.LLM_GATEWAY == LLMGatewayName.stanford:
            if not self.STANFORD_API_KEY:
                raise ValueError(
                    "LLM_GATEWAY=stanford requires STANFORD_API_KEY to be set in .env"
                )
            if not self.STANFORD_BASE_URL:
                raise ValueError(
                    "LLM_GATEWAY=stanford requires STANFORD_BASE_URL to be set in .env"
                )
        return self


_settings = Settings()

# ---------------------------------------------------------------------------
# Public API — module-level names that existing imports reference
# ---------------------------------------------------------------------------
LLM_GATEWAY = _settings.LLM_GATEWAY.value
SLAC_API_KEY = _settings.SLAC_API_KEY
STANFORD_API_KEY = _settings.STANFORD_API_KEY
MLFLOW_ENABLED = _settings.MLFLOW_ENABLED
MLFLOW_TRACKING_URI = _settings.MLFLOW_TRACKING_URI
MLFLOW_TOKEN = _settings.MLFLOW_TRACKING_TOKEN

# Slack — single source of truth (ui.config re-exports these).
SLACK_BOT_TOKEN = _settings.SLACK_BOT_TOKEN
SLACK_APP_TOKEN = _settings.SLACK_APP_TOKEN
SLACK_STEERING_CHANNEL_ID = _settings.SLACK_STEERING_CHANNEL_ID
SLACK_CHAT_CHANNEL_ID = _settings.SLACK_CHAT_CHANNEL_ID

# ---------------------------------------------------------------------------
# Gateway resolution
# ---------------------------------------------------------------------------
_GATEWAYS: dict[str, dict] = {
    "default": _DEFAULT_GATEWAY,
    "slac": {
        "url": _settings.SLAC_BASE_URL or None,
        "key": _settings.SLAC_API_KEY,
        "model_alias": _settings.SLAC_MODEL_ALIAS or None,
        "env": _gateway_extra_env("SLAC_"),
    },
    "stanford": {
        "url": _settings.STANFORD_BASE_URL or None,
        "key": _settings.STANFORD_API_KEY,
        "model_alias": _settings.STANFORD_MODEL_ALIAS or None,
        "env": _gateway_extra_env("STANFORD_"),
    },
}


def gateway_config() -> dict:
    """Return {url, key, model_alias, env} for the active LLM_GATEWAY."""
    return _GATEWAYS.get(LLM_GATEWAY, _DEFAULT_GATEWAY)


# ---------------------------------------------------------------------------
# Orchestrator cadences (internal)
# ---------------------------------------------------------------------------
ORCHESTRATOR_ENABLED = True
ORCHESTRATOR_TICK_S = 2.0
DEFAULT_BEAMTIME_HOURS = 48.0

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("ORCHESTRATION_DB_PATH", str(DATA_DIR / "orchestration.db"))
os.environ.setdefault("ORCHESTRATION_DB_PATH", DB_PATH)


def llm_enabled() -> bool:
    """True iff the LLM backend is usable (gateway key present)."""
    gw = gateway_config()
    return bool(gw["key"])
