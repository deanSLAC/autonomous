"""Cross-layer message contracts (no heavy imports — safe for adapters).

`InboundSlackMessage` replaces the old five-positional-string callback
signatures between `ui.adapters.slack_bridge` and `orchestration.api`
(`callback(text, author, channel, thread_ts, is_stop/source)`), where a
transposed argument was a silent routing bug. One frozen model is now
the contract both sides import.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

__all__ = ["ChatErrorEvent", "ChatReplyEvent", "InboundSlackMessage"]


class InboundSlackMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    author: str
    channel: Optional[str]
    thread_ts: Optional[str]
    # 'steering' messages come from the steering channel; chat sources
    # match ChatRouter.handle_inbound's `source` values.
    source: Literal["steering", "slack_chat", "slack_dm"]
    is_stop: bool = False


class ChatReplyEvent(BaseModel):
    """`chat_reply` WebSocket event — the dashboard chat dispatches on
    `type` and filters on `thread_key` (autonomy.js). This model is the
    single place those field names live on the server side."""

    model_config = ConfigDict(frozen=True)

    type: Literal["chat_reply"] = "chat_reply"
    session_id: str
    thread_key: Optional[str]
    text: str


class ChatErrorEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["chat_error"] = "chat_error"
    session_id: str
    thread_key: Optional[str]
    error: str
