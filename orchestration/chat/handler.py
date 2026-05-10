"""ChatRouter — routes inbound chat messages to spawned chat agents.

Architecture:
  * Each Slack thread / DM thread / UI session is one ChatSession row.
  * Each session has at most one in-flight `chat-claude.sh` agent.
  * When a new inbound message arrives mid-flight, it goes on a per-session
    queue and gets dispatched once the in-flight agent finishes.
  * `claude --resume <claude_session_id>` carries prior conversation
    context across spawns, so a thread reactivated a week later resumes
    the same session.
  * The agent's reply is posted back to Slack (if Slack-originated) and
    emitted as a `chat_reply` WebSocket event for the UI.

Threading model: the watcher (`_wait_and_dispatch`) is a daemon thread
that polls `agents.get_run(...)`. We use a simple polling loop rather
than the `_drain_and_finalize` thread because the spawn module is
already running its own drain — we just need to learn when it finished.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from orchestration.agents import get_run, spawn
from orchestration.chat.sessions import (
    compute_thread_key,
    get_or_create_session,
    log_chat_message,
    update_session_activity,
)
from orchestration.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


_CHAT_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "chat-claude.sh"

# Watcher poll cadence. spawn.py finalizes the row from a daemon drain
# thread; we poll DB every 0.5 s. Keep this small enough that latency feels
# interactive but not so small we hammer sqlite.
_POLL_INTERVAL_S = 0.5


class ChatRouter:
    """Per-thread chat router.

    One instance per process; share by injection rather than singleton
    globals so tests can stub it. The dependencies (`slack_post_chat_reply`,
    `slack_post_chat_root`, `ws_emit`) are passed in so this module
    doesn't transitively import the Slack adapter.
    """

    def __init__(
        self,
        *,
        slack_post_chat_reply: Callable[[str, str, str], None],
        ws_emit: Callable[[dict], Any],
        slack_post_chat_root: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        # slack_post_chat_reply(channel, thread_ts, text) -> None
        self._slack_post_chat_reply = slack_post_chat_reply
        # slack_post_chat_root(text) -> thread_ts | None  (creates a top-level
        # post in the configured chat channel; used to mirror UI sessions
        # so staff can see and join them in Slack).
        self._slack_post_chat_root = slack_post_chat_root
        # ws_emit(event_dict) -> None
        self._ws_emit = ws_emit

        # Per-session inbound queue. Entries: {"text", "author"}.
        self._queues: dict[str, list[dict]] = {}
        # Lock guards self._queues (the spawn check + queue append must
        # be atomic relative to the watcher's "pop next on completion").
        self._lock = threading.Lock()

    # -- public entry point --------------------------------------------

    def handle_inbound(
        self,
        *,
        text: str,
        author: str,
        channel: Optional[str],
        thread_ts: Optional[str],
        source: str,
        ui_session_id: Optional[str] = None,
        page: Optional[str] = None,
        page_context: Optional[Any] = None,
    ) -> dict:
        """Route an incoming chat message.

        Returns a small status dict for the UI / caller — primarily the
        session_id and whether the message was queued vs spawned.
        """
        try:
            thread_key = compute_thread_key(
                source, channel, thread_ts, ui_session_id=ui_session_id,
            )
        except ValueError as e:
            logger.warning("chat: bad inbound (%s)", e)
            return {"ok": False, "error": str(e)}

        # 1. Resolve / create the session row.
        session = get_or_create_session(
            thread_key=thread_key,
            source=source,
            slack_channel=channel,
            slack_thread_ts=thread_ts,
            ui_session_id=ui_session_id,
        )
        session_id = session["id"]

        # 2. UI-source mirroring: ensure the session has a Slack thread to
        #    post into so staff can see the conversation in Slack. Only
        #    needs to happen on the first UI inbound for this session.
        if (
            source == "ui"
            and not session.get("slack_thread_ts")
            and self._slack_post_chat_root is not None
        ):
            try:
                root_text = (
                    f":speech_balloon: *UI chat session*\n"
                    f"_thread_key: `{thread_key}`_\n"
                    f"*{author}*: {text[:1500]}"
                )
                root_ts = self._slack_post_chat_root(root_text)
                if root_ts:
                    # Persist the new thread_ts on the session.
                    from ui.config import SLACK_CHAT_CHANNEL_ID

                    update_session_activity(
                        session_id,
                        slack_channel=SLACK_CHAT_CHANNEL_ID or None,
                        slack_thread_ts=root_ts,
                    )
                    session["slack_thread_ts"] = root_ts
                    session["slack_channel"] = SLACK_CHAT_CHANNEL_ID or None
            except Exception as e:  # noqa: BLE001
                logger.warning("chat: UI->Slack mirror failed: %s", e)

        # 3. Mirror UI inbound to existing Slack thread for visibility,
        #    even after the first message.
        if (
            source == "ui"
            and session.get("slack_thread_ts")
            and session.get("slack_channel")
        ):
            try:
                self._slack_post_chat_reply(
                    session["slack_channel"],
                    session["slack_thread_ts"],
                    f"*{author}* (UI): {text}",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("chat: UI->Slack inbound mirror failed: %s", e)

        # 4. Log the inbound message.
        msg_source = {
            "slack_chat": "slack",
            "slack_dm": "dm",
            "ui": "ui",
        }.get(source, source)
        log_chat_message(
            session_id=session_id,
            direction="inbound",
            source=msg_source,
            author=author,
            text=text,
            slack_channel=session.get("slack_channel"),
            slack_thread_ts=session.get("slack_thread_ts"),
        )

        # 5. Decide: spawn now, or enqueue for later?
        with self._lock:
            active_run_id = session.get("active_agent_run_id")
            still_active = False
            if active_run_id:
                run = get_run(active_run_id)
                if run is not None and run.get("completed_at") is None:
                    still_active = True

            if still_active:
                self._queues.setdefault(session_id, []).append(
                    {
                        "text": text, "author": author,
                        "page": page, "page_context": page_context,
                    }
                )
                logger.info(
                    "chat[%s]: queued behind active run %s (%d in queue)",
                    thread_key, active_run_id, len(self._queues[session_id]),
                )
                return {
                    "ok": True,
                    "session_id": session_id,
                    "queued": True,
                    "thread_key": thread_key,
                }

            # Stale active_agent_run_id — clear it.
            if active_run_id and not still_active:
                update_session_activity(session_id, clear_active_agent=True)

            run_id = self._spawn_for(
                session, text, author,
                page=page, page_context=page_context,
            )
            return {
                "ok": True,
                "session_id": session_id,
                "queued": False,
                "run_id": run_id,
                "thread_key": thread_key,
            }

    # -- internal: spawn + watcher -------------------------------------

    def _spawn_for(
        self,
        session: dict,
        text: str,
        author: str,
        *,
        page: Optional[str] = None,
        page_context: Optional[Any] = None,
    ) -> str:
        """spawn() a chat-claude.sh agent for `text`; start watcher; return run_id.

        Caller is expected to be holding self._lock so we can mark the
        session's active_agent_run_id atomically.
        """
        thread_key = session["thread_key"]
        working_dir = Path(session["working_dir"])
        working_dir.mkdir(parents=True, exist_ok=True)

        # Phase-page chats pass live page_context with each turn so the agent
        # always sees current state (claude --resume otherwise carries stale
        # snapshots forward). The block sits between the first-turn orientation
        # header and the user's message.
        page_block = _format_page_context_block(page, page_context)

        # Build the seed prompt. claude --resume carries prior turns
        # automatically, so we only prepend an orientation header on the
        # very first turn (no existing claude_session_id).
        if not session.get("claude_session_id"):
            seed = (
                f"[Beamline chat session — sandbox at {working_dir}]\n"
                f"You are the BeamtimeHero chat agent. Use only the\n"
                f"`beamtimehero db`, `beamtimehero ref`, and `beamtimehero tool`\n"
                f"subtrees, plus Read. Do NOT attempt spec mutation.\n"
                f"{page_block}"
                f"\n"
                f"User ({author}): {text}"
            )
        else:
            seed = f"{page_block}{text}" if page_block else text

        run_id = spawn(
            agent_type="chat",
            task_text=f"chat: {text[:80]}",
            spawned_by=f"chat:{thread_key}",
            script_path=_CHAT_SCRIPT_PATH,
            seed_prompt=seed,
            working_dir=working_dir,
            claude_session_id=session.get("claude_session_id"),
        )

        update_session_activity(session["id"], active_agent_run_id=run_id)

        threading.Thread(
            target=self._wait_and_dispatch,
            args=(run_id, session["id"]),
            daemon=True,
            name=f"chat-watcher-{run_id}",
        ).start()

        logger.info(
            "chat[%s]: spawned chat agent run_id=%s", thread_key, run_id,
        )
        return run_id

    def _wait_and_dispatch(self, run_id: str, session_id: str) -> None:
        """Daemon thread: poll until the run completes, then post + dispatch next."""
        try:
            while True:
                run = get_run(run_id)
                if run is None:
                    logger.warning("chat watcher: run %s vanished", run_id)
                    return
                if run.get("completed_at"):
                    break
                time.sleep(_POLL_INTERVAL_S)

            # The run is done. Post the result.
            result_text = run.get("result") or "(no response)"
            claude_session_id = run.get("claude_session_id")

            update_session_activity(
                session_id,
                claude_session_id=claude_session_id,
                clear_active_agent=True,
            )

            from orchestration.chat.sessions import get_session_by_id

            session = get_session_by_id(session_id)
            if session is None:
                logger.warning("chat watcher: session %s vanished", session_id)
                return

            # Persist the outbound message.
            log_chat_message(
                session_id=session_id,
                direction="outbound",
                source="agent",
                author="AI Assistant",
                text=result_text,
                slack_channel=session.get("slack_channel"),
                slack_thread_ts=session.get("slack_thread_ts"),
            )

            # Push to Slack (if there's a thread to push to — true for
            # slack_chat / slack_dm always, and for ui sessions that
            # mirrored to Slack on first inbound).
            if session.get("slack_channel") and session.get("slack_thread_ts"):
                try:
                    self._slack_post_chat_reply(
                        session["slack_channel"],
                        session["slack_thread_ts"],
                        result_text,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("chat watcher: slack post failed: %s", e)

            # Push to UI via WS.
            try:
                self._ws_emit({
                    "type": "chat_reply",
                    "session_id": session_id,
                    "thread_key": session["thread_key"],
                    "text": result_text,
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("chat watcher: ws_emit failed: %s", e)

            # Dispatch the next queued message (if any).
            self._maybe_dispatch_next(session_id)
        except Exception:  # noqa: BLE001
            logger.exception("chat watcher crashed for run %s", run_id)

    def _maybe_dispatch_next(self, session_id: str) -> None:
        """Pop the next queued message for this session and spawn for it."""
        with self._lock:
            queue = self._queues.get(session_id) or []
            if not queue:
                return
            nxt = queue.pop(0)
            if not queue:
                self._queues.pop(session_id, None)

            # Re-fetch the session to get the freshly-persisted
            # claude_session_id so the next spawn uses --resume.
            from orchestration.chat.sessions import get_session_by_id

            session = get_session_by_id(session_id)
            if session is None:
                logger.warning(
                    "chat dispatch: session %s vanished while dispatching queue",
                    session_id,
                )
                return
            self._spawn_for(
                session, nxt["text"], nxt["author"],
                page=nxt.get("page"), page_context=nxt.get("page_context"),
            )


def _format_page_context_block(
    page: Optional[str], page_context: Optional[Any],
) -> str:
    """Render the page_context block that gets injected into the seed.

    Returns "" when there's nothing to render so callers can splice it in
    unconditionally without changing today's dashboard/Slack seed format.
    """
    if page_context is None:
        return ""
    try:
        body = json.dumps(page_context, indent=2, default=str, sort_keys=True)
    except (TypeError, ValueError):
        body = repr(page_context)
    label = f" — page={page}" if page else ""
    return f"\n[Phase page context{label}]\n{body}\n"


# ---------------------------------------------------------------------------
# Process-wide singleton (optional — UI server installs one in lifespan)
# ---------------------------------------------------------------------------

_SINGLETON: Optional[ChatRouter] = None


def set_chat_router_singleton(router: ChatRouter) -> None:
    global _SINGLETON
    _SINGLETON = router


def chat_router_singleton() -> Optional[ChatRouter]:
    return _SINGLETON
