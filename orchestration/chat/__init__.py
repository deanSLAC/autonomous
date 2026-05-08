"""orchestration.chat — per-thread chat agent routing.

Two surfaces, one router:

  * Slack chat channel (`SLACK_CHAT_CHANNEL_ID`) and bot DMs route into
    `ChatRouter.handle_inbound(...)` via the slack_bridge → orch_api hop.
  * UI chat-box POSTs to `/api/chat` route through the same handler so
    every conversation surface lives in the same `chatsession` table.

Each Slack thread / DM thread / UI session is one persistent ChatSession
row keyed by `thread_key`. A single `chat-claude.sh` agent runs at a
time per session; concurrent inbound messages are queued and dispatched
once the in-flight agent finishes. `claude --resume` (driven by the
session's `claude_session_id`) makes a one-week-old thread feel like it
just paused.
"""

from orchestration.chat.handler import (
    ChatRouter,
    chat_router_singleton,
    set_chat_router_singleton,
)
from orchestration.chat.sessions import (
    archive_session,
    compute_thread_key,
    get_active_session_by_key,
    get_or_create_session,
    get_session_by_id,
    list_recent_sessions,
    list_session_messages,
    log_chat_message,
    update_session_activity,
)

__all__ = [
    "ChatRouter",
    "chat_router_singleton",
    "set_chat_router_singleton",
    "compute_thread_key",
    "get_or_create_session",
    "archive_session",
    "get_active_session_by_key",
    "get_session_by_id",
    "update_session_activity",
    "log_chat_message",
    "list_session_messages",
    "list_recent_sessions",
]
