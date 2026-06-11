"""Slack bridge for BeamtimeHero.

Two distinct flows + DMs:

* Steering channel (`SLACK_STEERING_CHANNEL_ID`): staff guidance for the
  autonomous run. Each Slack post (top-level or thread reply) is enqueued
  to the `staffguidance` table via `add_steering(...)`. Slack provenance
  (channel, thread_ts) is captured so the orchestrator can reply in the
  same thread when the agent finishes responding. STOP messages are
  flagged for the orchestrator's fast-path.
* Chat channel (`SLACK_CHAT_CHANNEL_ID`): chat with the agent. Each
  thread is its own continuous chat session.
* Bot DMs (`channel_type == "im"`): same routing as chat.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Callable

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from orchestration.messages import InboundSlackMessage
from ui.config import (
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
    SLACK_STEERING_CHANNEL_ID,
    SLACK_CHAT_CHANNEL_ID,
)

logger = logging.getLogger(__name__)


# Match an explicit STOP command — the entire message (modulo surrounding
# whitespace, an optional `!` prefix, and trailing `.`/`!` punctuation) must
# be the literal token "stop". Anything else is conversational prose.
#
# Accepts: "stop", "STOP", "!stop", "  !Stop  ", "stop.", "stop!", "STOP!!!".
# Rejects: "stop the run", "stop now", "When you finish, stop before X",
#          "stopping the press", "please halt", "stop_now", "Stopper".
_STOP_PATTERN = re.compile(r"^\s*!?stop[!.]*\s*$", re.IGNORECASE)


def is_stop_text(text: str) -> bool:
    """True iff `text` is a STOP command (see _STOP_PATTERN)."""
    return bool(_STOP_PATTERN.match(text or ""))


def _truncate(text: str, limit: int = 3000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n_(truncated)_"


class SlackBridge:
    """Bidirectional bridge between BeamtimeHero web app and Slack."""

    def __init__(self):
        # Both inbound callbacks take a single InboundSlackMessage —
        # the typed contract lives in orchestration.messages.
        self._on_steering_message: (
            Callable[[InboundSlackMessage], None] | None
        ) = None
        # message.source ∈ {'slack_chat', 'slack_dm'}
        self._on_chat_message: (
            Callable[[InboundSlackMessage], None] | None
        ) = None
        # callback(intervention_id, status, staff_name) for !resume / !deny
        self._on_intervention_resolve: (
            Callable[[str, str, str], None] | None
        ) = None
        # callback(dir_name) for !setdir command — returns reply string
        self._on_setdir: Callable[[str], str] | None = None

        self._app: App | None = None
        self._handler: SocketModeHandler | None = None
        self._bot_user_id: str | None = None

    # -- callback wiring -----------------------------------------------

    def set_steering_callback(
        self, callback: Callable[[InboundSlackMessage], None]
    ) -> None:
        """Set callback for messages in the steering Slack channel."""
        self._on_steering_message = callback

    def set_chat_callback(
        self, callback: Callable[[InboundSlackMessage], None]
    ) -> None:
        """Set callback for chat-channel messages and DMs."""
        self._on_chat_message = callback

    def set_intervention_resolve_callback(
        self, callback: Callable[[str, str, str], None]
    ) -> None:
        """Set callback for !resume / !deny commands. Signature: (id, status, staff_name)."""
        self._on_intervention_resolve = callback

    def set_setdir_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for !setdir command. Returns status message."""
        self._on_setdir = callback

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Start Slack bot in a background thread."""
        if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
            logger.warning("Slack tokens not configured — Slack bridge disabled")
            return

        self._app = App(token=SLACK_BOT_TOKEN)
        self._register_handlers()

        # Get our own bot user ID so we can ignore our own messages
        try:
            auth = self._app.client.auth_test()
            self._bot_user_id = auth["user_id"]
        except Exception as e:
            logger.warning("Could not get bot user ID: %s", e)

        self._handler = SocketModeHandler(self._app, SLACK_APP_TOKEN)

        thread = threading.Thread(target=self._handler.start, daemon=True)
        thread.start()
        logger.info(
            "Slack bridge started (Steering: %s, Chat: %s)",
            SLACK_STEERING_CHANNEL_ID,
            SLACK_CHAT_CHANNEL_ID,
        )

    def _resolve_staff_name(self, user_id: str, client) -> str:
        """Look up a Slack user's display name."""
        if not user_id:
            return "Staff"
        try:
            info = client.users_info(user=user_id)
            profile = info["user"].get("profile", {})
            return (
                profile.get("display_name")
                or profile.get("real_name")
                or user_id
            )
        except Exception:
            return user_id

    # -- inbound handlers ----------------------------------------------

    def _register_handlers(self) -> None:
        @self._app.event("message")
        def handle_message(event, client):
            # Ignore bot messages (including our own)
            if event.get("bot_id") or event.get("subtype"):
                return

            channel = event.get("channel", "")
            channel_type = event.get("channel_type", "")
            thread_ts = event.get("thread_ts")
            msg_ts = event.get("ts", "")
            text = event.get("text", "").strip()
            user_id = event.get("user", "")

            if not text:
                return

            # --- !resume / !deny <intervention_id> (any channel) ---
            if text.startswith("!resume") or text.startswith("!deny"):
                parts = text.split(maxsplit=1)
                status = "resolved" if parts[0] == "!resume" else "denied"
                if len(parts) > 1 and self._on_intervention_resolve:
                    iid = parts[1].strip()
                    staff_name = self._resolve_staff_name(user_id, client)
                    try:
                        self._on_intervention_resolve(iid, status, staff_name)
                        client.chat_postMessage(
                            channel=channel,
                            text=f"Intervention `{iid}` marked {status} by {staff_name}.",
                            thread_ts=thread_ts or msg_ts,
                        )
                    except Exception as e:
                        client.chat_postMessage(
                            channel=channel,
                            text=f"Error: {e}",
                            thread_ts=thread_ts or msg_ts,
                        )
                return

            # --- !setdir command (any channel) ---
            if text.startswith("!setdir"):
                dir_name = text[len("!setdir"):].strip()
                if dir_name and self._on_setdir:
                    try:
                        result = self._on_setdir(dir_name)
                        client.chat_postMessage(
                            channel=channel,
                            text=result,
                            thread_ts=thread_ts or msg_ts,
                        )
                    except Exception as e:
                        client.chat_postMessage(
                            channel=channel,
                            text=f"Error: {e}",
                            thread_ts=thread_ts or msg_ts,
                        )
                return

            # --- DMs to the bot — route to chat callback with source='slack_dm' ---
            if channel_type == "im":
                staff_name = self._resolve_staff_name(user_id, client)
                root_ts = thread_ts or msg_ts
                logger.info("Staff DM from %s: %s", staff_name, text[:100])
                if self._on_chat_message:
                    self._on_chat_message(InboundSlackMessage(
                        text=text, author=staff_name, channel=channel,
                        thread_ts=root_ts, source="slack_dm",
                    ))
                return

            # --- Steering channel ---
            if channel == SLACK_STEERING_CHANNEL_ID:
                staff_name = self._resolve_staff_name(user_id, client)
                root_ts = thread_ts or msg_ts
                stop_flag = is_stop_text(text)
                logger.info(
                    "Steering message from %s (is_stop=%s): %s",
                    staff_name, stop_flag, text[:100],
                )
                if self._on_steering_message:
                    self._on_steering_message(InboundSlackMessage(
                        text=text, author=staff_name, channel=channel,
                        thread_ts=root_ts, source="steering",
                        is_stop=stop_flag,
                    ))
                return

            # --- Chat channel ---
            if channel == SLACK_CHAT_CHANNEL_ID:
                staff_name = self._resolve_staff_name(user_id, client)
                root_ts = thread_ts or msg_ts
                logger.info("Chat message from %s: %s", staff_name, text[:100])
                if self._on_chat_message:
                    self._on_chat_message(InboundSlackMessage(
                        text=text, author=staff_name, channel=channel,
                        thread_ts=root_ts, source="slack_chat",
                    ))
                return

            # Anything else — ignore.

    # -- outbound posting ----------------------------------------------

    def post_steering_reply(
        self, channel: str, thread_ts: str, text: str,
    ) -> None:
        """Reply to a steering Slack message in its thread."""
        if not self._app:
            logger.info("[slack/steering-reply] %s", text[:200])
            return
        try:
            self._app.client.chat_postMessage(
                channel=channel,
                text=_truncate(text),
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error("Failed to post steering reply: %s", e)

    def post_chat_reply(
        self, channel: str, thread_ts: str, text: str,
    ) -> None:
        """Post an agent chat reply back to the same Slack thread."""
        if not self._app:
            logger.info("[slack/chat-reply] %s", text[:200])
            return
        try:
            self._app.client.chat_postMessage(
                channel=channel,
                text=_truncate(text),
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error("Failed to post chat reply: %s", e)

    def post_chat_root(self, text: str) -> str | None:
        """Post a top-level message in the CHAT channel; return the new thread_ts.

        Used to create a Slack thread that mirrors a UI chat session, so
        staff can see and join UI conversations from Slack. Returns None
        if Slack isn't configured (UI-only mode).
        """
        if not self._app or not SLACK_CHAT_CHANNEL_ID:
            logger.info("[slack/chat-root] %s", text[:200])
            return None
        try:
            result = self._app.client.chat_postMessage(
                channel=SLACK_CHAT_CHANNEL_ID,
                text=_truncate(text),
            )
            return result.get("ts") if isinstance(result, dict) else result["ts"]
        except Exception as e:
            logger.error("Failed to post chat root: %s", e)
            return None

    def post_status_update(
        self, text: str, *, thread_ts: str | None = None,
    ) -> None:
        """Manual status post — top-level message in the CHAT channel.

        If `thread_ts` is supplied, post into that thread; else top-level.
        """
        if not self._app or not SLACK_CHAT_CHANNEL_ID:
            logger.info("[slack/status] %s", text[:200])
            return
        try:
            self._app.client.chat_postMessage(
                channel=SLACK_CHAT_CHANNEL_ID,
                text=f":robot_face: *Autonomy status update*\n{_truncate(text)}",
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error("Failed to post status update: %s", e)

    def post_intervention(
        self, intervention_id: str, kind: str, detail: str,
    ) -> None:
        """Post an intervention request so staff can resolve it.

        Top-level message in the STEERING channel — staff reply
        `!resume <id>` (in the thread or anywhere) to clear it, or
        `!deny <id>` to cancel.
        """
        if not self._app or not SLACK_STEERING_CHANNEL_ID:
            logger.info("[slack/intervention] %s %s", kind, detail)
            return
        try:
            body = (
                f":pause_button: *Human intervention required* ({kind})\n"
                f"{detail}\n\n"
                f"Reply with `!resume {intervention_id}` when ready, "
                f"or `!deny {intervention_id}` to cancel."
            )
            self._app.client.chat_postMessage(
                channel=SLACK_STEERING_CHANNEL_ID,
                text=body,
            )
        except Exception as e:
            logger.error("Failed to post intervention request: %s", e)
