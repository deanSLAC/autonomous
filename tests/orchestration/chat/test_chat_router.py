"""Smoke tests for ChatRouter.handle_inbound and thread-key semantics.

These pin the chat contract shared by the dashboard UI and Slack before
the chat-consolidation / opencode-removal refactors: thread_key shapes,
spawn-vs-queue behavior, seed construction, and the chat_reply WS event.
All DB / spawn / Slack dependencies are stubbed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.chat import handler as handler_mod  # noqa: E402
from orchestration.chat.handler import ChatRouter  # noqa: E402
from orchestration.chat.sessions import compute_thread_key  # noqa: E402


# -- compute_thread_key ------------------------------------------------------

def test_thread_key_ui():
    assert compute_thread_key("ui", None, None, ui_session_id="abc123") == "ui:abc123"


def test_thread_key_slack_chat():
    assert compute_thread_key("slack_chat", "C01", "171.5") == "slack:C01:171.5"


def test_thread_key_slack_dm():
    assert compute_thread_key("slack_dm", "D01", "172.5") == "dm:D01:172.5"


def test_thread_key_ui_requires_session_id():
    with pytest.raises(ValueError):
        compute_thread_key("ui", None, None)


def test_thread_key_unknown_source():
    with pytest.raises(ValueError):
        compute_thread_key("smoke_signal", "C01", "1.0")


# -- ChatRouter --------------------------------------------------------------

@pytest.fixture
def router_env(monkeypatch, tmp_path):
    """ChatRouter with every external dependency stubbed.

    Returns a state dict capturing spawns, logged messages, ws emits,
    and Slack posts.
    """
    state = {
        "spawns": [],          # kwargs passed to spawn()
        "logged": [],          # kwargs passed to log_chat_message()
        "ws": [],              # events passed to ws_emit
        "slack_replies": [],   # (channel, thread_ts, text)
        "session": {
            "id": "sess-1",
            "thread_key": None,  # filled by fake get_or_create_session
            "source": None,
            "claude_session_id": None,
            "working_dir": str(tmp_path / "wd"),
            "active_agent_run_id": None,
            "slack_channel": None,
            "slack_thread_ts": None,
            "ui_session_id": None,
        },
        "runs": {},            # run_id -> run dict for get_run
    }

    def fake_get_or_create_session(*, thread_key, source, **kw):
        state["session"]["thread_key"] = thread_key
        state["session"]["source"] = source
        return dict(state["session"])

    def fake_spawn(**kw):
        state["spawns"].append(kw)
        run_id = f"run-{len(state['spawns'])}"
        state["runs"][run_id] = {"completed_at": None}
        return run_id

    monkeypatch.setattr(handler_mod, "get_or_create_session", fake_get_or_create_session)
    monkeypatch.setattr(handler_mod, "spawn", fake_spawn)
    monkeypatch.setattr(handler_mod, "get_run", lambda rid: state["runs"].get(rid))
    monkeypatch.setattr(handler_mod, "log_chat_message", lambda **kw: state["logged"].append(kw))
    monkeypatch.setattr(handler_mod, "update_session_activity", lambda *a, **kw: None)

    router = ChatRouter(
        slack_post_chat_reply=lambda ch, ts, txt: state["slack_replies"].append((ch, ts, txt)),
        ws_emit=lambda ev: state["ws"].append(ev),
        slack_post_chat_root=None,  # no Slack mirroring in these tests
    )
    return router, state


def test_ui_inbound_spawns_and_returns_thread_key(router_env):
    router, state = router_env
    result = router.handle_inbound(
        text="hello", author="ui-user", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    assert result["ok"] is True
    assert result["thread_key"] == "ui:abc123"
    assert result["session_id"] == "sess-1"
    assert result["queued"] is False
    assert len(state["spawns"]) == 1


def test_first_turn_seed_has_orientation_header(router_env):
    router, state = router_env
    router.handle_inbound(
        text="what is the latest scan?", author="dean", channel=None,
        thread_ts=None, source="ui", ui_session_id="abc123",
    )
    seed = state["spawns"][0]["seed_prompt"]
    assert "Beamline chat session" in seed
    assert "User (dean): what is the latest scan?" in seed


def test_resumed_turn_seed_is_bare_text(router_env):
    router, state = router_env
    state["session"]["claude_session_id"] = "claude-uuid-1"
    router.handle_inbound(
        text="and the one before?", author="dean", channel=None,
        thread_ts=None, source="ui", ui_session_id="abc123",
    )
    seed = state["spawns"][0]["seed_prompt"]
    assert seed == "and the one before?"
    assert state["spawns"][0]["claude_session_id"] == "claude-uuid-1"


def test_inbound_message_is_logged(router_env):
    router, state = router_env
    router.handle_inbound(
        text="hi", author="dean", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    assert len(state["logged"]) == 1
    logged = state["logged"][0]
    assert logged["direction"] == "inbound"
    assert logged["source"] == "ui"
    assert logged["text"] == "hi"


def test_slack_chat_inbound_uses_slack_thread_key(router_env):
    router, state = router_env
    result = router.handle_inbound(
        text="hello from slack", author="staff", channel="C01",
        thread_ts="171.5", source="slack_chat",
    )
    assert result["thread_key"] == "slack:C01:171.5"
    assert state["logged"][0]["source"] == "slack"


def test_second_message_queues_behind_active_run(router_env):
    router, state = router_env
    first = router.handle_inbound(
        text="first", author="dean", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    # Simulate the session now carrying the active run id (still running).
    state["session"]["active_agent_run_id"] = first["run_id"]

    second = router.handle_inbound(
        text="second", author="dean", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    assert second["queued"] is True
    assert len(state["spawns"]) == 1  # no second spawn while run-1 is active


def test_completed_run_does_not_queue(router_env):
    router, state = router_env
    first = router.handle_inbound(
        text="first", author="dean", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    state["session"]["active_agent_run_id"] = first["run_id"]
    state["runs"][first["run_id"]]["completed_at"] = "2026-06-11T12:00:00"

    second = router.handle_inbound(
        text="second", author="dean", channel=None, thread_ts=None,
        source="ui", ui_session_id="abc123",
    )
    assert second["queued"] is False
    assert len(state["spawns"]) == 2
