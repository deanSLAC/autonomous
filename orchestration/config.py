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
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Paths (derived from repo layout, not configurable)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_DIR = PROJECT_ROOT / "context"
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class AgentBackend(str, Enum):
    claude_code = "claude_code"
    opencode = "opencode"


class LLMGatewayName(str, Enum):
    slac = "slac"
    stanford = "stanford"
    default = "default"


# ---------------------------------------------------------------------------
# Gateway sub-model — one per upstream provider
# ---------------------------------------------------------------------------
class _GatewayBlock:
    """Resolved at runtime from env vars with the gateway's prefix."""

    __slots__ = ("url", "key", "model_alias", "env")

    def __init__(self, prefix: str) -> None:
        self.url: str | None = os.environ.get(f"{prefix}BASE_URL") or None
        self.key: str = os.environ.get(f"{prefix}API_KEY") or ""
        self.model_alias: str | None = os.environ.get(f"{prefix}MODEL_ALIAS") or None
        env_block: dict[str, str] = {}
        skip = {"BASE_URL", "API_KEY", "MODEL_ALIAS"}
        for k, v in os.environ.items():
            if k.startswith(prefix) and k.removeprefix(prefix) not in skip:
                env_block[k.removeprefix(prefix)] = v
        self.env = env_block

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "key": self.key,
            "model_alias": self.model_alias,
            "env": dict(self.env),
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
    AGENT_BACKEND: AgentBackend
    LLM_GATEWAY: LLMGatewayName
    CLAUDE_MODEL: str = ""
    SLAC_API_KEY: str = ""
    STANFORD_API_KEY: str = ""

    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    SLACK_LLM_CHANNEL_ID: str = ""
    SLACK_USERS_CHANNEL_ID: str = ""

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
            if not os.environ.get("SLAC_BASE_URL"):
                raise ValueError(
                    "LLM_GATEWAY=slac requires SLAC_BASE_URL to be set in .env"
                )
        elif self.LLM_GATEWAY == LLMGatewayName.stanford:
            if not self.STANFORD_API_KEY:
                raise ValueError(
                    "LLM_GATEWAY=stanford requires STANFORD_API_KEY to be set in .env"
                )
            if not os.environ.get("STANFORD_BASE_URL"):
                raise ValueError(
                    "LLM_GATEWAY=stanford requires STANFORD_BASE_URL to be set in .env"
                )
        return self


_settings = Settings()

# ---------------------------------------------------------------------------
# Public API — module-level names that existing imports reference
# ---------------------------------------------------------------------------
AGENT_BACKEND = _settings.AGENT_BACKEND.value
LLM_GATEWAY = _settings.LLM_GATEWAY.value
SLAC_API_KEY = _settings.SLAC_API_KEY
STANFORD_API_KEY = _settings.STANFORD_API_KEY
MLFLOW_ENABLED = _settings.MLFLOW_ENABLED
MLFLOW_TRACKING_URI = _settings.MLFLOW_TRACKING_URI
MLFLOW_TOKEN = _settings.MLFLOW_TRACKING_TOKEN

# ---------------------------------------------------------------------------
# Gateway resolution
# ---------------------------------------------------------------------------
_GATEWAYS: dict[str, dict] = {
    "default": _DEFAULT_GATEWAY,
    "slac": _GatewayBlock("SLAC_").as_dict(),
    "stanford": _GatewayBlock("STANFORD_").as_dict(),
}


def gateway_config() -> dict:
    """Return {url, key, model_alias, env} for the active LLM_GATEWAY."""
    return _GATEWAYS.get(LLM_GATEWAY, _DEFAULT_GATEWAY)


# ---------------------------------------------------------------------------
# Opencode internals (operators don't touch these)
# ---------------------------------------------------------------------------
OPENCODE_HOST = "127.0.0.1"
OPENCODE_PORT = 4096
OPENCODE_URL = f"http://{OPENCODE_HOST}:{OPENCODE_PORT}"
OPENCODE_BIN = os.getenv(
    "OPENCODE_BIN", str(Path.home() / ".opencode" / "bin" / "opencode")
)
OPENCODE_MESSAGE_TIMEOUT_S = None

# ---------------------------------------------------------------------------
# Orchestrator cadences (internal)
# ---------------------------------------------------------------------------
ORCHESTRATOR_ENABLED = True
ORCHESTRATOR_TICK_S = 5.0
STATUS_POST_INTERVAL_S = 900.0
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
