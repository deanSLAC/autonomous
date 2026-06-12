"""Print `export KEY=VALUE` lines mapping the active LLM gateway onto the
ANTHROPIC_* environment the `claude` CLI reads.

Evaluated by scripts/_agent-common.sh at agent spawn, so every spawned
agent (phase tiles, chat, tester) talks to the gateway configured in
.env (LLM_GATEWAY + <GATEWAY>_* vars). This replaces the per-turn env
wiring that lived in the retired in-process ClaudeCodeClient.send()
path — without it, spawned agents silently fall back to whatever auth
the `claude` binary has on disk.

When LLM_GATEWAY is "default" nothing is printed and the parent env is
left untouched (claude uses its on-disk auth, as before).
"""

from __future__ import annotations

import shlex


def export_lines() -> list[str]:
    from orchestration.config import CLAUDE_MODEL, gateway_config

    gw = gateway_config()
    lines: list[str] = []
    if gw.get("url"):
        lines.append(f"export ANTHROPIC_BASE_URL={shlex.quote(gw['url'])}")
    if gw.get("key"):
        lines.append(f"export ANTHROPIC_AUTH_TOKEN={shlex.quote(gw['key'])}")
    # CLAUDE_MODEL (.env) overrides the gateway's model alias if set —
    # useful for one-off A/B testing of model versions.
    model = CLAUDE_MODEL or gw.get("model_alias")
    if model:
        lines.append(f"export ANTHROPIC_MODEL={shlex.quote(model)}")
    # Gateway extras (model defaults, beta-feature gates, prompt-caching
    # toggles) — already stripped of their SLAC_/STANFORD_ prefix by
    # orchestration.config._gateway_extra_env.
    for k, v in (gw.get("env") or {}).items():
        lines.append(f"export {k}={shlex.quote(str(v))}")
    return lines


if __name__ == "__main__":
    print("\n".join(export_lines()))
