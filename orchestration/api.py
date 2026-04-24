"""orchestration.api — the single surface the UI talks to.

Everything the UI or Slack adapter needs goes through this module:

  * startup wiring (`configure(app)`) installs the FastAPI lifespan,
    opencode health check, Slack callbacks, and orchestrator.
  * chat: `handle_chat(text, experiment_id, page, page_context)` builds
    the planner-state prefix and hands the turn to the conversation
    service. The UI routers do not construct `OpenCodeClient` or touch
    `planner.snapshot` directly.
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

from beamline_tools.spec import spec_cmd
from orchestration.agent.conversation import ConversationService, set_turn_sink
from orchestration.agent.opencode_client import OpenCodeClient
from orchestration.config import OPENCODE_URL, llm_enabled
from orchestration.planner import planner as _planner
from orchestration.planner.loop import Orchestrator, get_orchestrator, set_orchestrator
from orchestration.planner.staff_guidance import coordinator
from orchestration.plan_store.client import (
    get_experiment_plan,
    list_guidance,
    list_open_interventions,
    log_plan_edit,
    record_phase_transition,
    reset_run_state,
)
from orchestration.plan_store.session import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process-wide state owned by orchestration — injected into the UI at startup.
# ---------------------------------------------------------------------------

_conversation: Optional[ConversationService] = None
_event_emitter: Callable[[dict], Any] = lambda evt: None
_slack_status_post: Callable[[str], Any] = lambda text: None
_insight_record_turn: Optional[Callable[[dict], dict]] = None


def set_event_emitter(fn: Callable[[dict], Any]) -> None:
    global _event_emitter
    _event_emitter = fn


def set_slack_status_post(fn: Callable[[str], Any]) -> None:
    global _slack_status_post
    _slack_status_post = fn


def set_insight_record_turn(fn: Callable[[dict], dict]) -> None:
    global _insight_record_turn
    _insight_record_turn = fn


# ---------------------------------------------------------------------------
# Chat / LLM
# ---------------------------------------------------------------------------

def agent_reachable() -> bool:
    if not llm_enabled():
        return False
    try:
        return OpenCodeClient().health_check()
    except Exception:
        return False


def current_experiment_id() -> Optional[str]:
    """Convenience for UI callers that don't want to import beamline_tools.spec."""
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
    client = OpenCodeClient()
    if not client.health_check():
        return None
    _conversation = ConversationService(client)
    return _conversation


def reset_conversation() -> None:
    global _conversation
    if llm_enabled():
        _conversation = ConversationService(OpenCodeClient())
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


def handle_chat(
    user_text: str,
    *,
    experiment_id: str | None = None,
    page: str | None = None,
    page_context: dict | None = None,
) -> dict:
    """Process a single chat turn and return {response, images, experiment_id}.

    Raises:
        RuntimeError: if the LLM is disabled or opencode is unreachable.
    """
    conv = _ensure_conversation()
    if conv is None:
        if not llm_enabled():
            raise RuntimeError("LLM disabled: SLAC_API_KEY required")
        raise RuntimeError(f"opencode server at {OPENCODE_URL} is not reachable")
    exp_id = _resolve_chat_experiment_id(experiment_id)
    prefix = _build_chat_context_prefix(exp_id, page=page, page_context=page_context)
    augmented = f"{prefix}\n\n[User/operator]: {user_text}"
    result = conv.handle_message(augmented)
    return {"response": result.text, "images": result.images, "experiment_id": exp_id}


def handle_staff_llm(text: str, staff_name: str) -> dict:
    """Route a !LLM-tagged Slack message through the agent."""
    conv = _ensure_conversation()
    if conv is None:
        raise RuntimeError("LLM not available")
    result = conv.handle_staff_llm(text, staff_name)
    return {"text": result.text, "images": result.images}


# ---------------------------------------------------------------------------
# Orchestrator lifecycle
# ---------------------------------------------------------------------------

def start_orchestrator(experiment_id: str) -> None:
    orch = get_orchestrator()
    if orch is None:
        raise RuntimeError("Orchestrator not initialized (is opencode reachable?)")
    orch.start(experiment_id)


def pause_orchestrator() -> None:
    orch = get_orchestrator()
    if orch is not None:
        orch.pause()


def resume_orchestrator() -> None:
    orch = get_orchestrator()
    if orch is not None:
        orch.resume()


def stop_orchestrator() -> None:
    orch = get_orchestrator()
    if orch is not None:
        orch.stop()


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

def on_staff_message(text: str, staff_name: str) -> None:
    """A message in the user-facing Slack channel — logged as guidance."""
    _event_emitter({"type": "staff_message", "name": staff_name, "text": text})
    coordinator.record_guidance(
        experiment_id=spec_cmd.get_experiment_id(),
        source="slack", author=staff_name, text=text,
    )


def on_llm_thread_reply(text: str, staff_name: str) -> dict | None:
    """A !LLM-tagged staff message — feed it into the conversation + guidance queue.

    Returns the LLM's reply dict {text, images} so the Slack adapter can
    post it back to the thread. Returns None if the LLM is disabled.
    """
    _event_emitter({"type": "staff_in_llm", "name": staff_name, "text": text})
    coordinator.record_guidance(
        experiment_id=spec_cmd.get_experiment_id(),
        source="slack-steering", author=staff_name, text=text,
    )
    conv = _ensure_conversation()
    if conv is None:
        return None
    result = conv.handle_staff_llm(text, staff_name)
    _event_emitter({
        "type": "assistant", "text": result.text, "images": result.images,
    })
    return {"text": result.text, "images": result.images}


_dm_conversations: dict[str, ConversationService] = {}


def on_dm_message(text: str, staff_name: str, dm_thread_key: str) -> str | None:
    """A DM to the bot — each thread gets its own ConversationService."""
    if dm_thread_key not in _dm_conversations:
        if not llm_enabled():
            logger.warning("Cannot handle DM: SLAC_API_KEY required")
            return None
        _dm_conversations[dm_thread_key] = ConversationService(OpenCodeClient())
    dm_conv = _dm_conversations[dm_thread_key]
    try:
        result = dm_conv.handle_staff_llm(text, staff_name)
    except Exception as e:
        logger.error("DM conversation error: %s", e, exc_info=True)
        return f"Error: {e}"
    return result.text


def on_setdir(dir_name: str) -> str:
    """Operator ran `!setdir` in Slack — rewire bl_config + reset conversation."""
    from beamline_tools.scans import bl_config
    from beamline_tools.scans.local_data import clear_cache

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

    # 1. DB init (both sqlite files)
    try:
        from orchestration.plan_store.init_db import init_db
        init_db()
    except Exception as e:
        logger.error("init_db failed: %s", e, exc_info=True)

    # 2. Conversation (LLM client) — gated on opencode reachability
    if llm_enabled():
        try:
            client = OpenCodeClient()
            if client.health_check():
                _conversation = ConversationService(client)
                logger.info(
                    "opencode session service initialized (model=%s url=%s)",
                    client.model, OPENCODE_URL,
                )
            else:
                logger.warning(
                    "opencode server at %s is not reachable yet — agent disabled "
                    "until it comes up.",
                    OPENCODE_URL,
                )
        except Exception as e:
            logger.error("Failed to initialize opencode client: %s", e)

    # 3. Orchestrator
    if _conversation is not None:
        orch = Orchestrator(
            _conversation,
            emit=lambda evt: _event_emitter(evt),
            slack_status_post=lambda text: _slack_status_post(text),
        )
        set_orchestrator(orch)
        logger.info("Orchestrator initialized")

    # 4. Autonomy callback wiring — intervention notifier + phase approval
    #    channel. These read back into orchestration via `coordinator`.
    from beamline_tools.tool_catalog import autonomy_tools

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

    autonomy_tools.set_intervention_notifier(_notify_intervention)
    autonomy_tools.set_phase_approval_requester(_phase_approval_requester)

    # 5. Turn sink (insight panel)
    if _insight_record_turn is not None:
        set_turn_sink(lambda payload: _event_emitter({
            "type": "turn_complete", "turn": _insight_record_turn(payload),
        }))

    yield
