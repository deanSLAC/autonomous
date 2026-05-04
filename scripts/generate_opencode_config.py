"""Generate opencode.json from .env so there's one source of truth.

Reads LLM_GATEWAY and the matching {PREFIX}_* env vars, writes the
provider/model config that opencode needs.  Run before `opencode serve`.

Usage (from start.sh):
    python scripts/generate_opencode_config.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from orchestration.config import LLM_GATEWAY, gateway_config  # noqa: E402

_MODEL_LIMITS = {
    "opus":   {"context": 1_000_000, "output": 65_536},
    "sonnet": {"context": 200_000,   "output": 65_536},
    "haiku":  {"context": 200_000,   "output": 32_768},
}

_TIER_PATTERN = re.compile(r"ANTHROPIC_DEFAULT_(\w+)_MODEL")

_GATEWAY_DISPLAY = {
    "slac": "SLAC AI Gateway",
    "stanford": "Stanford AI Playground",
}

OUT = ROOT / "opencode.json"


def _tier_for_model_id(model_id: str) -> str:
    lower = model_id.lower()
    if "opus" in lower:
        return "opus"
    if "haiku" in lower:
        return "haiku"
    return "sonnet"


def main() -> None:
    if LLM_GATEWAY == "default":
        print(
            "ERROR: AGENT_BACKEND=opencode requires a gateway "
            "(slac or stanford), not 'default'.",
            file=sys.stderr,
        )
        sys.exit(2)

    gw = gateway_config()
    prefix = LLM_GATEWAY.upper() + "_"
    base_url = gw["url"]
    api_key_var = f"{prefix}API_KEY"

    # Discover models from the ANTHROPIC_DEFAULT_*_MODEL env vars in the
    # gateway's env block.
    models: dict[str, dict] = {}
    for env_key, model_id in gw["env"].items():
        m = _TIER_PATTERN.match(env_key)
        if not m:
            continue
        tier = _tier_for_model_id(model_id)
        limits = _MODEL_LIMITS.get(tier, _MODEL_LIMITS["sonnet"])
        display = f"Claude {tier.title()}"
        models[model_id] = {
            "name": display,
            "limit": limits,
        }

    if not models:
        print(
            f"ERROR: no ANTHROPIC_DEFAULT_*_MODEL vars found for "
            f"gateway '{LLM_GATEWAY}'. Check .env.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Pick the default model: use MODEL_ALIAS to find the right tier,
    # or fall back to the first model discovered.
    alias = gw["model_alias"]
    default_model_id = None
    if alias:
        alias_upper = alias.upper()
        env_key = f"ANTHROPIC_DEFAULT_{alias_upper}_MODEL"
        default_model_id = gw["env"].get(env_key)
    if not default_model_id:
        default_model_id = next(iter(models))

    config = {
        "$schema": "https://opencode.ai/config.json",
        "share": "disabled",
        "autoupdate": False,
        "experimental": {"openTelemetry": False},
        "model": f"{LLM_GATEWAY}/{default_model_id}",
        "provider": {
            LLM_GATEWAY: {
                "npm": "@ai-sdk/openai-compatible",
                "name": _GATEWAY_DISPLAY.get(LLM_GATEWAY, LLM_GATEWAY),
                "options": {
                    "baseURL": f"{base_url}/v1",
                    "apiKey": f"{{env:{api_key_var}}}",
                },
                "models": models,
            },
        },
    }

    OUT.write_text(json.dumps(config, indent=2) + "\n")
    print(f"wrote {OUT} (gateway={LLM_GATEWAY}, model={config['model']})")


if __name__ == "__main__":
    main()
