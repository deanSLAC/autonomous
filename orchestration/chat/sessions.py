"""DB CRUD for ChatSession + ChatMessage.

One ChatSession per Slack thread / DM thread / UI session. The thread_key
column is the unique namespace identifier:

  * 'slack:<channel>:<root_ts>' — Slack chat-channel thread
  * 'dm:<channel>:<root_ts>'    — Slack DM thread
  * 'ui:<ui_session_id>'        — UI chat-box session

Sessions persist forever; archival is explicit (UI clear button, etc.).
A "reactivated" thread (one that was archived) doesn't reuse the row —
get_or_create_session looks up by `thread_key AND archived_at IS NULL`,
so archiving and re-keying creates a fresh row.

Returns dicts (not ORM rows) from every accessor so callers don't have
to keep a Session open across a function boundary.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import select

from orchestration.config import PROJECT_ROOT
from orchestration.plan_store.models import ChatMessage, ChatSession
from orchestration.plan_store.session import get_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAT_SESSIONS_DIR = PROJECT_ROOT / "data" / "chat_sessions"


_UNSAFE_FS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_dirname(thread_key: str) -> str:
    """Make a thread_key safe for use as a directory name on the filesystem."""
    return _UNSAFE_FS.sub("_", thread_key).strip("_") or "session"


def compute_thread_key(
    source: str,
    channel: Optional[str],
    thread_ts: Optional[str],
    ui_session_id: Optional[str] = None,
) -> str:
    """Yield the canonical thread_key for a chat surface.

    * source='slack_chat'   -> 'slack:<channel>:<thread_ts>'
    * source='slack_dm'     -> 'dm:<channel>:<thread_ts>'
    * source='ui'           -> 'ui:<ui_session_id>'
    """
    if source == "slack_chat":
        return f"slack:{channel}:{thread_ts}"
    if source == "slack_dm":
        return f"dm:{channel}:{thread_ts}"
    if source == "ui":
        if not ui_session_id:
            raise ValueError("compute_thread_key(source='ui') requires ui_session_id")
        return f"ui:{ui_session_id}"
    raise ValueError(f"compute_thread_key: unknown source {source!r}")


def _session_to_dict(row: ChatSession) -> dict:
    return {
        "id": row.id,
        "thread_key": row.thread_key,
        "source": row.source,
        "claude_session_id": row.claude_session_id,
        "working_dir": row.working_dir,
        "active_agent_run_id": row.active_agent_run_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_activity_at": (
            row.last_activity_at.isoformat() if row.last_activity_at else None
        ),
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "slack_channel": row.slack_channel,
        "slack_thread_ts": row.slack_thread_ts,
        "ui_session_id": row.ui_session_id,
    }


def _message_to_dict(row: ChatMessage) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "direction": row.direction,
        "source": row.source,
        "author": row.author,
        "text": row.text,
        "slack_channel": row.slack_channel,
        "slack_thread_ts": row.slack_thread_ts,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def get_active_session_by_key(thread_key: str) -> Optional[dict]:
    """Most recent non-archived row for that thread_key, or None."""
    with get_session() as session:
        stmt = (
            select(ChatSession)
            .where(ChatSession.thread_key == thread_key)
            .where(ChatSession.archived_at.is_(None))  # type: ignore[union-attr]
            .order_by(ChatSession.created_at.desc())  # type: ignore[union-attr]
            .limit(1)
        )
        row = session.exec(stmt).first()
        return _session_to_dict(row) if row else None


def get_or_create_session(
    *,
    thread_key: str,
    source: str,
    slack_channel: Optional[str] = None,
    slack_thread_ts: Optional[str] = None,
    ui_session_id: Optional[str] = None,
) -> dict:
    """Look up a non-archived session by `thread_key`, creating one if missing.

    Side effects:
      * The session's working_dir (`data/chat_sessions/<safe(thread_key)>/`)
        is created on disk.
    """
    existing = get_active_session_by_key(thread_key)
    if existing is not None:
        # Make sure the working_dir still exists (it could have been pruned).
        try:
            Path(existing["working_dir"]).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return existing

    safe = _safe_dirname(thread_key)
    working_dir = _CHAT_SESSIONS_DIR / safe
    working_dir.mkdir(parents=True, exist_ok=True)

    row = ChatSession(
        thread_key=thread_key,
        source=source,
        working_dir=str(working_dir),
        slack_channel=slack_channel,
        slack_thread_ts=slack_thread_ts,
        ui_session_id=ui_session_id,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _session_to_dict(row)


def archive_session(session_id: str) -> Optional[dict]:
    """Set archived_at=now and tombstone the thread_key.

    The `thread_key` column has a UNIQUE index (see models.ChatSession),
    so we mutate the archived row's thread_key to `<key>#archived:<id>`.
    That frees the original key for a fresh `get_or_create_session` call
    (e.g. UI Clear button followed by a new message in the same Slack
    thread or UI tab) without losing the audit trail of past chats.
    Used by the UI clear button.
    """
    with get_session() as session:
        row = session.get(ChatSession, session_id)
        if row is None:
            return None
        row.archived_at = datetime.now()
        if not row.thread_key.startswith("#archived:"):
            row.thread_key = f"#archived:{row.id}:{row.thread_key}"
        session.add(row)
        session.commit()
        session.refresh(row)
        return _session_to_dict(row)


def update_session_activity(
    session_id: str,
    *,
    claude_session_id: Optional[str] = None,
    active_agent_run_id: Optional[str] = None,
    slack_channel: Optional[str] = None,
    slack_thread_ts: Optional[str] = None,
    clear_active_agent: bool = False,
) -> None:
    """Refresh `last_activity_at`; optionally update other fields.

    `active_agent_run_id` semantics:
      * non-None      -> set
      * None and not `clear_active_agent` -> leave unchanged
      * None and `clear_active_agent`     -> clear (set to None)

    `slack_channel` / `slack_thread_ts` are likewise leave-unchanged when None.
    """
    with get_session() as session:
        row = session.get(ChatSession, session_id)
        if row is None:
            return
        row.last_activity_at = datetime.now()
        if claude_session_id is not None:
            row.claude_session_id = claude_session_id
        if active_agent_run_id is not None:
            row.active_agent_run_id = active_agent_run_id
        elif clear_active_agent:
            row.active_agent_run_id = None
        if slack_channel is not None:
            row.slack_channel = slack_channel
        if slack_thread_ts is not None:
            row.slack_thread_ts = slack_thread_ts
        session.add(row)
        session.commit()


def get_session_by_id(session_id: str) -> Optional[dict]:
    with get_session() as session:
        row = session.get(ChatSession, session_id)
        return _session_to_dict(row) if row else None


def list_recent_sessions(
    *, source: Optional[str] = None, limit: int = 50,
) -> list[dict]:
    with get_session() as session:
        stmt = select(ChatSession)
        if source is not None:
            stmt = stmt.where(ChatSession.source == source)
        stmt = stmt.order_by(ChatSession.last_activity_at.desc()).limit(limit)  # type: ignore[union-attr]
        return [_session_to_dict(r) for r in session.exec(stmt).all()]


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------

def log_chat_message(
    *,
    session_id: str,
    direction: str,
    source: str,
    author: str,
    text: str,
    slack_channel: Optional[str] = None,
    slack_thread_ts: Optional[str] = None,
) -> dict:
    """Insert one ChatMessage row. `direction` ∈ {'inbound','outbound'}."""
    row = ChatMessage(
        session_id=session_id,
        direction=direction,
        source=source,
        author=author,
        text=text,
        slack_channel=slack_channel,
        slack_thread_ts=slack_thread_ts,
    )
    with get_session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _message_to_dict(row)


def list_session_messages(session_id: str, *, limit: int = 200) -> list[dict]:
    """All messages in a session, oldest first."""
    with get_session() as session:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.timestamp)  # type: ignore[union-attr]
            .limit(limit)
        )
        return [_message_to_dict(r) for r in session.exec(stmt).all()]
