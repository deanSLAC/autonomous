"""orchestration.api — the single surface the UI talks to.

Everything the UI or Slack adapter needs goes through this module:

  * startup wiring (`configure(app)`) installs the FastAPI lifespan,
    opencode health check, Slack callbacks, and orchestrator.
  * chat: `set_chat_handler(fn)` lets `orchestration.chat.ChatRouter`
    register itself; `on_chat_message(...)` routes Slack chat / DM
    inbound messages to the router. The router spawns chat-claude.sh
    subprocesses per session and posts replies back via Slack + WS.
  * passthroughs for the plan store and staff guidance.

This module also owns the spec_cmd experiment-id setter so the tools
layer never needs to write to its own context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from beamline_tools.spec_control import spec_cmd
from orchestration.agent.conversation import ConversationService
from orchestration.agent.claude_code_client import ClaudeCodeClient
from orchestration.agent.opencode_client import OpenCodeClient
from orchestration.config import AGENT_BACKEND, OPENCODE_URL, llm_enabled
from orchestration.planner import planner as _planner
from orchestration.planner.loop import Orchestrator, get_orchestrator, set_orchestrator
from orchestration.planner.staff_guidance import coordinator
from orchestration.plan_store.session import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process-wide state owned by orchestration — injected into the UI at startup.
# ---------------------------------------------------------------------------

_conversation: Optional[ConversationService] = None
_event_emitter: Callable[[dict], Any] = lambda evt: None
_slack_status_post: Callable[[str], Any] = lambda text: None
_slack_post_steering_reply: Callable[[str, str, str], Any] = lambda c, t, s: None


def _make_agent_client():
    """Construct the agent client per AGENT_BACKEND. Both adapters expose
    the same interface so ConversationService doesn't care which one runs."""
    if AGENT_BACKEND == "claude_code":
        return ClaudeCodeClient()
    if AGENT_BACKEND not in ("opencode", ""):
        logger.warning(
            "Unknown AGENT_BACKEND=%r; falling back to opencode.", AGENT_BACKEND,
        )
    return OpenCodeClient()


def set_event_emitter(fn: Callable[[dict], Any]) -> None:
    global _event_emitter
    _event_emitter = fn


def set_slack_status_post(fn: Callable[[str], Any]) -> None:
    global _slack_status_post
    _slack_status_post = fn


def set_slack_post_steering_reply(fn: Callable[[str, str, str], Any]) -> None:
    global _slack_post_steering_reply
    _slack_post_steering_reply = fn


# ---------------------------------------------------------------------------
# Chat / LLM
# ---------------------------------------------------------------------------

def agent_reachable() -> bool:
    if not llm_enabled():
        return False
    try:
        return _make_agent_client().health_check()
    except Exception:
        return False


def current_experiment_id() -> Optional[str]:
    """Convenience for UI callers that don't want to import beamline_tools.spec_control."""
    return spec_cmd.get_experiment_id()


def set_active_experiment(experiment_id: str, phase: str = "setup") -> None:
    """Orchestration writes context that the tools layer reads."""
    spec_cmd.set_phase(phase, experiment_id=experiment_id)


def get_conversation() -> Optional[ConversationService]:
    return _conversation


def _ensure_conversation() -> Optional[ConversationService]:
    global _conversation
    if _conversation is not None:
        return _conversation
    if not llm_enabled():
        return None
    client = _make_agent_client()
    if not client.health_check():
        return None
    _conversation = ConversationService(client)
    return _conversation


def reset_conversation() -> None:
    global _conversation
    if llm_enabled():
        _conversation = ConversationService(_make_agent_client())
    else:
        _conversation = None


def _resolve_chat_experiment_id(requested: str | None) -> Optional[str]:
    if requested:
        return requested
    orch = get_orchestrator()
    if orch and orch.state.experiment_id:
        return orch.state.experiment_id
    try:
        from orchestration.plan_store.models import Experiment
        from sqlmodel import select
        with get_session() as session:
            row = session.exec(
                select(Experiment).order_by(Experiment.created_at.desc()).limit(1)
            ).first()
            return row.id if row else None
    except Exception as e:
        logger.warning("chat: latest-experiment lookup failed: %s", e)
        return None


def _build_chat_context_prefix(
    experiment_id: str | None,
    page: str | None = None,
    page_context: dict | None = None,
) -> str:
    phase = spec_cmd.get_phase()
    lines: list[str] = []
    if experiment_id:
        try:
            snap = _planner.snapshot(experiment_id)
            lines.append(snap.to_system_context())
        except Exception as e:
            logger.warning("chat: planner snapshot failed for %s: %s", experiment_id, e)
            lines.append(f"[PLANNER STATE]\n  phase: {phase}\n  (snapshot unavailable)")
    else:
        lines.append(
            f"[PLANNER STATE]\n  phase: {phase}\n"
            "  (no experiment configured yet — suggest the user open /config)"
        )
    if page or page_context:
        ctx_lines = ["[PAGE CONTEXT]"]
        if page:
            ctx_lines.append(f"  page: {page}")
        if isinstance(page_context, dict):
            for k, v in page_context.items():
                try:
                    rendered = json.dumps(v, default=str) if not isinstance(v, str) else v
                except Exception:
                    rendered = str(v)
                ctx_lines.append(f"  {k}: {rendered}")
        ctx_lines.append(
            "  The user is viewing the page above. Use the beamline tools "
            "(get_latest_scan, list_scans, read_scan, plot_scan, etc.) to "
            "fetch data relevant to this page when they ask about it."
        )
        lines.append("\n".join(ctx_lines))
    lines.append(
        "Forward phase moves go through the `transition_phase` tool; "
        "preconditions gate every transition."
    )
    return "\n\n".join(lines)


# `handle_chat()` was the legacy synchronous chat path that ran a
# ConversationService turn inline. It's been replaced by the chat router
# in `orchestration.chat.handler`, which spawns chat-claude.sh agents
# per ChatSession and pushes replies back via Slack + WebSocket.
# `_build_chat_context_prefix` / `_resolve_chat_experiment_id` are kept
# above — they may still be useful for any callers that want to build a
# planner-state prefix (and removing them would be a separate cleanup).


# ---------------------------------------------------------------------------
# Orchestrator state snapshot — the master start/pause/resume/stop loop
# was retired in favour of per-phase tile launchers, so the only thing
# the UI still asks for is the read-only snapshot.
# ---------------------------------------------------------------------------

def orchestrator_snapshot() -> dict:
    orch = get_orchestrator()
    if orch is None:
        return {"initialized": False}
    snap = orch.snapshot()
    snap["initialized"] = True
    return snap


# ---------------------------------------------------------------------------
# Staff guidance / interventions (passthroughs)
# ---------------------------------------------------------------------------

def record_slack_guidance(text: str, staff_name: str, *, source: str = "slack") -> None:
    coordinator.record_guidance(
        experiment_id=spec_cmd.get_experiment_id(),
        source=source, author=staff_name, text=text,
    )


async def resolve_intervention_async(intervention_id: str, status: str, resolver: str) -> None:
    await coordinator.resolve(intervention_id, status=status, resolver=resolver)


# ---------------------------------------------------------------------------
# Slack routing — called by the Slack adapter in `ui.adapters.slack_bridge`
# via callbacks registered at startup. Orchestration owns the routing;
# the adapter is just transport.
# ---------------------------------------------------------------------------

def on_steering_message(
    text: str, author: str, channel: str, thread_ts: str, is_stop: bool,
) -> None:
    """Slack steering channel inbound — record on the steering queue.

    The orchestrator state machine picks the row up, routes it to a control
    agent, and posts the agent's response back to `(channel, thread_ts)`.
    """
    from orchestration.plan_store.client import add_steering

    _event_emitter({
        "type": "steering_message",
        "name": author,
        "text": text,
        "is_stop": is_stop,
    })
    add_steering(
        experiment_id=spec_cmd.get_experiment_id(),
        source="slack-steering",
        author=author,
        text=text,
        slack_channel=channel,
        slack_thread_ts=thread_ts,
        is_stop=is_stop,
    )


_chat_handler: Optional[Callable[..., None]] = None


def set_chat_handler(fn: Callable[..., None]) -> None:
    """The chat-handler subagent will register the actual chat router here."""
    global _chat_handler
    _chat_handler = fn


def on_chat_message(
    text: str, author: str, channel: str, thread_ts: str, source: str,
) -> None:
    """Slack chat channel or DM inbound — hand off to the chat handler.

    The chat handler is wired via `set_chat_handler(fn)`; until it is set,
    we just log the message so nothing is silently dropped. The chat
    handler subagent will replace this stub with full routing (per-thread
    ChatSession + outbound Slack reply).
    """
    _event_emitter({
        "type": "chat_message",
        "name": author,
        "text": text,
        "source": source,
    })
    handler = _chat_handler
    if handler is None:
        logger.info(
            "chat msg [%s/%s/%s/%s]: %s",
            source, channel, thread_ts, author, text[:120],
        )
        return
    handler(
        text=text, author=author, channel=channel,
        thread_ts=thread_ts, source=source,
    )


def on_setdir(dir_name: str) -> str:
    """Operator ran `!setdir` in Slack — rewire bl_config + reset conversation."""
    from beamline_tools import config as bl_config
    from beamline_tools.spec_data.local_data import clear_cache

    bl_config.set_scan_dir(dir_name)
    clear_cache()
    reset_conversation()
    return f"Scan directory set to `{bl_config.BL_SCAN_DIR}`. Conversation reset."


def on_intervention_resolve(intervention_id: str, status: str, staff_name: str,
                             event_loop: asyncio.AbstractEventLoop | None) -> None:
    """Slack `!resume`/`!deny` — resolve the intervention on the orchestration loop."""
    if event_loop is None:
        logger.warning("No event loop yet; cannot resolve intervention from Slack")
        return
    asyncio.run_coroutine_threadsafe(
        coordinator.resolve(intervention_id, status=status,
                            resolver=f"slack:{staff_name}"),
        event_loop,
    )


# ---------------------------------------------------------------------------
# Lifespan / configuration — called from ui.server.app.create_app()
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan. Owns: DB init, orchestrator init, Slack wiring."""
    global _conversation

    event_loop = asyncio.get_running_loop()

    # 0. MLflow health check — make a broken token loud at startup so a
    #    deployment without observability is obvious, not silent.
    try:
        from orchestration.observability import mlflow_logging
        ok, reason = mlflow_logging.health_check()
        if ok:
            logger.info("mlflow tracing: %s", reason)
        elif reason == "MLFLOW_ENABLED=0":
            logger.info("mlflow tracing disabled (MLFLOW_ENABLED=0)")
        else:
            logger.warning(
                "!!! MLFLOW UNREACHABLE — observability degraded — "
                "fix .env or restart (%s)", reason,
            )
            _event_emitter({
                "type": "orchestrator_event",
                "level": "warning",
                "message": f"MLflow unreachable: {reason}",
            })
    except Exception as e:
        logger.warning("mlflow health check raised: %s", e)

    # 1. DB init (both sqlite files)
    try:
        from orchestration.plan_store.init_db import init_db
        init_db()
    except Exception as e:
        logger.error("init_db failed: %s", e, exc_info=True)

    # 1b. Purge orphan AgentRun rows from a previous server crash —
    #     killpg any still-running claude subprocesses we own and mark
    #     the rows completed before the orchestrator state machine
    #     reads from `agentrun`.
    try:
        from orchestration.agents import purge_orphans_at_startup
        n_purged = await asyncio.to_thread(purge_orphans_at_startup)
        if n_purged:
            logger.info("startup: purged %d orphan agent run(s)", n_purged)
    except Exception as e:
        logger.error("purge_orphans_at_startup failed: %s", e, exc_info=True)

    # 2. Conversation (LLM client) — gated on the configured backend.
    if llm_enabled():
        try:
            client = _make_agent_client()
            if client.health_check():
                _conversation = ConversationService(client)
                logger.info(
                    "agent session service initialized (backend=%s model=%s)",
                    AGENT_BACKEND, client.model,
                )
            else:
                if AGENT_BACKEND == "claude_code":
                    logger.warning(
                        "claude binary not invokable — agent disabled until "
                        "`claude --version` succeeds.",
                    )
                else:
                    logger.warning(
                        "opencode server at %s is not reachable yet — agent disabled "
                        "until it comes up.",
                        OPENCODE_URL,
                    )
        except Exception as e:
            logger.error("Failed to initialize agent client: %s", e)

    # 3. Orchestrator — no longer depends on the LLM. Control agents get
    #    their own claude session via scripts/control-claude.sh; the loop
    #    itself just polls SQL and spawns/kills/Slack-posts.
    orch = Orchestrator(
        emit=lambda evt: _event_emitter(evt),
        slack_status_post=lambda text: _slack_status_post(text),
        slack_post_steering_reply=lambda c, t, s: _slack_post_steering_reply(c, t, s),
    )
    set_orchestrator(orch)
    logger.info("Orchestrator initialized")

    # 4. Autonomy callback wiring — intervention notifier + phase approval
    #    channel. These read back into orchestration via `coordinator`.
    from beamline_tools.tool_catalog import tools as _tools_module

    async def _notify_intervention(intervention_id: str, detail: str) -> None:
        _event_emitter({
            "type": "intervention_created",
            "id": intervention_id,
            "detail": detail,
        })

    async def _phase_approval_requester(kind: str, detail: str) -> dict:
        return await coordinator.request_approval(
            kind=kind, detail=detail,
            experiment_id=spec_cmd.get_experiment_id(),
            notify=_notify_intervention,
        )

    _tools_module.set_intervention_notifier(_notify_intervention)
    _tools_module.set_phase_approval_requester(_phase_approval_requester)

    # 5. Orchestrator polling tick — auto-respawn the planner after each
    #    new CollectionScan, redispatch deferred steering rows that named
    #    a target_agent_type, and handle STOP rows.
    from orchestration.planner.orchestrator_tick import run_forever as _tick_run
    tick_task = asyncio.create_task(_tick_run(), name="orchestrator_tick")

    try:
        yield
    finally:
        # Teardown order:
        #   1. cancel the orchestrator tick (don't spawn anything new mid-shutdown)
        #   2. kill any agent subprocesses still flagged active
        tick_task.cancel()
        try:
            await tick_task
        except (asyncio.CancelledError, Exception):
            pass

        try:
            from orchestration.agents import kill_all_at_shutdown
            await kill_all_at_shutdown()
        except Exception as e:
            logger.error("kill_all_at_shutdown failed: %s", e, exc_info=True)
