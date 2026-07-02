"""Primary -> fallback gateway-key selection for spawned claude agents.

The key is baked into the `claude -p` subprocess env at spawn, so failover
happens at spawn time: `gateway_env.export_lines()` picks the primary unless it
is cooling down from a recent rate-limit, in which case it uses the fallback.
A rate-limited turn trips that cooldown via `config.note_gateway_rate_limited`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamtimehero_cli.llm import KeyPool  # noqa: E402
from orchestration import config  # noqa: E402
from orchestration.agent import gateway_env  # noqa: E402


def _fake_gw():
    return {
        "url": "https://gw.example",
        "keys": [("SLAC_API_KEY_PRIMARY", "PRIMARY"), ("SLAC_API_KEY", "FALLBACK")],
        "model_alias": None,
        "env": {},
    }


def test_export_lines_prefers_primary_then_fallback(monkeypatch):
    pool = KeyPool([("SLAC_API_KEY_PRIMARY", "PRIMARY"), ("SLAC_API_KEY", "FALLBACK")])
    monkeypatch.setattr(config, "gateway_config", _fake_gw)
    monkeypatch.setattr(config, "gateway_key_pool", lambda: pool)
    monkeypatch.setattr(config, "CLAUDE_MODEL", "")

    lines = gateway_env.export_lines()
    assert "export ANTHROPIC_AUTH_TOKEN=PRIMARY" in lines
    assert "export ANTHROPIC_BASE_URL=https://gw.example" in lines

    # Primary rate-limited -> next spawn uses the fallback key.
    pool.mark_locked_out("SLAC_API_KEY_PRIMARY")
    lines2 = gateway_env.export_lines()
    assert "export ANTHROPIC_AUTH_TOKEN=FALLBACK" in lines2


def test_note_gateway_rate_limited_trips_active_key(monkeypatch):
    pool = KeyPool([("SLAC_API_KEY_PRIMARY", "PRIMARY"), ("SLAC_API_KEY", "FALLBACK")])
    monkeypatch.setattr(config, "gateway_key_pool", lambda: pool)

    assert pool.active()[0] == "SLAC_API_KEY_PRIMARY"
    config.note_gateway_rate_limited()
    assert pool.active()[0] == "SLAC_API_KEY"


def test_looks_rate_limited():
    assert config.looks_rate_limited("HTTP 429 Too Many Requests")
    assert config.looks_rate_limited("rate_limit_error")
    assert config.looks_rate_limited("gateway overloaded")
    assert not config.looks_rate_limited("all good, here is your answer")
    assert not config.looks_rate_limited("")


def test_export_lines_single_key_backward_compatible(monkeypatch):
    # Only the existing key set (no primary) -> that key is exported, as before.
    pool = KeyPool([("SLAC_API_KEY_PRIMARY", ""), ("SLAC_API_KEY", "ONLY")])
    monkeypatch.setattr(config, "gateway_config", _fake_gw)
    monkeypatch.setattr(config, "gateway_key_pool", lambda: pool)
    monkeypatch.setattr(config, "CLAUDE_MODEL", "")

    lines = gateway_env.export_lines()
    assert "export ANTHROPIC_AUTH_TOKEN=ONLY" in lines
