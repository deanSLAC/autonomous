"""Autonomous Beamline Agent — FastAPI application.

Single FastAPI process that serves:

  * The experiment configuration form (/config).
  * The autonomous-run dashboard (/dashboard).
  * The chat-style assistant (/ — legacy beamtimehero UI).
  * The agent tool API (/api/chat, /api/tools, ...).
  * The config + dashboard + orchestrator routers (/api/**).
  * A WebSocket (/ws) for live status broadcast.

On startup it wires the Slack bridge, Orchestrator, ConversationService,
and StaffCoordinator together so staff guidance + intervention
resolutions flow end-to-end.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# Make the server/ directory the primary import root, and expose the
# sibling beamline_lib package (legacy analysis tools).
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "beamline_lib"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Simulation bootstrap MUST run before bl_config is imported, because
# bl_config reads BL_SCAN_DIR / BL_LOGS_DIR at import time.
from dotenv import load_dotenv
load_dotenv()
import simulation as _sim
_SIM_INFO = _sim.bootstrap()

from config import (
    BASE_PATH, STATIC_DIR, PROJECT_ROOT, PORT,
    llm_enabled, OPENCODE_URL,
)
from opencode_client import OpenCodeClient
from conversation import ConversationService, set_turn_sink
from slack_bridge import SlackBridge

# Autonomy wiring
from db import init_db as init_db_module
from orchestrator.loop import Orchestrator, set_orchestrator
from orchestrator.staff_guidance import coordinator
from spec import spec_cmd
from tools import autonomy_tools
from ui import config_api, dashboard_api, orchestrator_api, plan_api, insight_api


logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --- Global state ---
slack_bridge = SlackBridge()
conversation: ConversationService | None = None
orchestrator: Orchestrator | None = None
connected_ws: set[WebSocket] = set()
_event_loop: asyncio.AbstractEventLoop | None = None


# ===========================================================================
# Broadcast helpers
# ===========================================================================

async def broadcast_ws(message: dict):
    payload = json.dumps(message, default=str)
    disconnected = set()
    for ws in connected_ws:
        try:
            await ws.send_text(payload)
        except Exception:
            disconnected.add(ws)
    connected_ws.difference_update(disconnected)


def _broadcast(msg: dict):
    if _event_loop is None:
        logger.debug("No event loop available for WebSocket broadcast")
        return
    asyncio.run_coroutine_threadsafe(broadcast_ws(msg), _event_loop)


def _on_turn_complete(payload: dict) -> None:
    """Sink for ConversationService — store + broadcast each turn."""
    entry = insight_api.record_turn(payload)
    _broadcast({"type": "turn_complete", "turn": entry})


# ===========================================================================
# Slack callbacks — staff guidance + intervention resolution
# ===========================================================================

def on_staff_message(text: str, staff_name: str):
    _broadcast({"type": "staff_message", "name": staff_name, "text": text})
    coordinator.record_guidance(
        experiment_id=spec_cmd.get_experiment_id(),
        source="slack", author=staff_name, text=text,
    )


def on_llm_thread_reply(text: str, staff_name: str):
    """Staff reply in the LLM channel thread. Feeds both the chat turn and the guidance queue."""
    _broadcast({"type": "staff_in_llm", "name": staff_name, "text": text})
    coordinator.record_guidance(
        experiment_id=spec_cmd.get_experiment_id(),
        source="slack-steering", author=staff_name, text=text,
    )
    if conversation:
        result = conversation.handle_staff_llm(text, staff_name)
        _broadcast({
            "type": "assistant",
            "text": result.text,
            "images": result.images,
        })
        slack_bridge.post_llm_response(result.text)


_dm_conversations: dict[str, ConversationService] = {}


def on_dm_message(text: str, staff_name: str, dm_thread_key: str):
    global _dm_conversations
    if dm_thread_key not in _dm_conversations:
        if not llm_enabled():
            logger.warning("Cannot handle DM: SLAC_API_KEY required")
            return
        client = OpenCodeClient()
        _dm_conversations[dm_thread_key] = ConversationService(client)
    dm_conv = _dm_conversations[dm_thread_key]
    try:
        result = dm_conv.handle_staff_llm(text, staff_name)
    except Exception as e:
        logger.error("DM conversation error: %s", e, exc_info=True)
        result_text = f"Error: {e}"
    else:
        result_text = result.text
    channel, thread_ts = dm_thread_key.split(":", 1)
    slack_bridge.post_dm_reply(channel, thread_ts, result_text)


def on_setdir(dir_name: str) -> str:
    global conversation
    import bl_config
    from local_data import clear_cache
    bl_config.set_scan_dir(dir_name)
    clear_cache()
    if llm_enabled():
        client = OpenCodeClient()
        conversation = ConversationService(client)
    slack_bridge.reset_thread()
    return f"Scan directory set to `{bl_config.BL_SCAN_DIR}`. Conversation reset."


def on_intervention_resolve(intervention_id: str, status: str, staff_name: str):
    if _event_loop is None:
        logger.warning("No event loop yet; cannot resolve intervention from Slack")
        return
    asyncio.run_coroutine_threadsafe(
        coordinator.resolve(intervention_id, status=status, resolver=f"slack:{staff_name}"),
        _event_loop,
    )


# ===========================================================================
# Intervention notifier + phase approval requester
# ===========================================================================

async def _notify_intervention(intervention_id: str, detail: str) -> None:
    _broadcast({"type": "intervention_created", "id": intervention_id, "detail": detail})
    try:
        slack_bridge.post_intervention(intervention_id, "intervention", detail)
    except Exception as e:
        logger.error("Slack post_intervention failed: %s", e)


async def _phase_approval_requester(kind: str, detail: str) -> dict:
    experiment_id = spec_cmd.get_experiment_id()
    return await coordinator.request_approval(
        kind=kind, detail=detail,
        experiment_id=experiment_id,
        notify=_notify_intervention,
    )


# ===========================================================================
# Lifespan
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global conversation, orchestrator, _event_loop

    _event_loop = asyncio.get_running_loop()

    try:
        init_db_module.init_db()
    except Exception as e:
        logger.error("init_db failed: %s", e, exc_info=True)

    if llm_enabled():
        try:
            client = OpenCodeClient()
            if client.health_check():
                conversation = ConversationService(client)
                logger.info("opencode session service initialized (model=%s url=%s)",
                            client.model, OPENCODE_URL)
            else:
                logger.warning(
                    "opencode server at %s is not reachable yet — agent disabled "
                    "until it comes up. Start it with scripts/start_opencode.sh.",
                    OPENCODE_URL,
                )
        except Exception as e:
            logger.error("Failed to initialize opencode client: %s", e)

    slack_bridge.set_staff_callback(on_staff_message)
    slack_bridge.set_llm_thread_callback(on_llm_thread_reply)
    slack_bridge.set_dm_callback(on_dm_message)
    slack_bridge.set_setdir_callback(on_setdir)
    slack_bridge.set_intervention_resolve_callback(on_intervention_resolve)
    slack_bridge.start()

    if conversation is not None:
        orchestrator = Orchestrator(
            conversation,
            emit=lambda evt: _broadcast(evt),
            slack_status_post=lambda text: slack_bridge.post_status_update(text),
        )
        set_orchestrator(orchestrator)
        logger.info("Orchestrator initialized")

    autonomy_tools.set_intervention_notifier(_notify_intervention)
    autonomy_tools.set_phase_approval_requester(_phase_approval_requester)
    set_turn_sink(_on_turn_complete)

    yield


# ===========================================================================
# FastAPI app
# ===========================================================================

app = FastAPI(title="Autonomous Beamline Agent", lifespan=lifespan)

app.mount(
    f"{BASE_PATH}/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)

app.include_router(config_api.router)
app.include_router(dashboard_api.router)
app.include_router(orchestrator_api.router)
app.include_router(plan_api.router)
app.include_router(insight_api.router)


@app.get(f"{BASE_PATH}/health")
async def health():
    return {
        "status": "ok",
        "phase": spec_cmd.get_phase(),
        "simulation": bool(_SIM_INFO.get("enabled")),
    }


@app.get(f"{BASE_PATH}/insight")
async def insight_page():
    return FileResponse(STATIC_DIR / "insight" / "index.html", media_type="text/html")


# ---- Page routes ---------------------------------------------------------

async def _index_page():
    # Legacy chat-only UI has been retired; the dashboard now hosts both
    # the chat panel and a collapsible "What the agent can do" panel.
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{BASE_PATH}/dashboard", status_code=307)


if BASE_PATH:
    app.get(BASE_PATH)(_index_page)
    app.get(f"{BASE_PATH}/")(_index_page)
else:
    app.get("/")(_index_page)


@app.get(f"{BASE_PATH}/config")
async def config_page():
    return FileResponse(STATIC_DIR / "config" / "index.html", media_type="text/html")


@app.get(f"{BASE_PATH}/dashboard")
async def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard" / "index.html", media_type="text/html")


@app.get(f"{BASE_PATH}/history", response_class=HTMLResponse)
async def history_page():
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<title>Action log</title>'
        '<link rel="stylesheet" href="/static/dashboard/static/dashboard.css">'
        '<link rel="stylesheet" href="/static/dashboard/autonomy.css">'
        '</head><body>'
        '<div class="topbar"><div class="topbar-left">'
        '<div class="topbar-title">Action &amp; Query log</div></div></div>'
        '<div style="padding:24px"><div class="panel">'
        '<div class="panel-header">Recent actions (last 200)</div>'
        '<div id="actions" class="action-tape"></div></div></div>'
        '<script>(async () => {'
        'const r = await fetch("/api/dashboard/action_log?limit=200");'
        'const j = await r.json();'
        'const el = document.getElementById("actions");'
        'el.innerHTML = (j.actions || []).map(a => {'
        'const badge = a.success === 1 ? "ok" : a.success === 0 ? "err" : "pend";'
        'const txt = a.success === 1 ? "OK" : a.success === 0 ? "FAIL" : "…";'
        'return `<div class="action-row" title="${(a.justification||"").replace(/"/g,"&quot;")}">'
        '<span class="phase">${(a.timestamp||"").slice(11,19)}</span>'
        '<span class="phase">${a.phase||""}</span>'
        '<span class="cmd">${a.command}</span>'
        '<span class="just">${(a.justification||"").slice(0,180)}</span>'
        '<span class="badge ${badge}">${txt}</span></div>`;}).join("");})();</script>'
        '</body></html>'
    )


# ---- Chat API ------------------------------------------------------------

@app.post(f"{BASE_PATH}/api/chat")
async def chat(payload: dict):
    global conversation
    user_text = payload.get("message", "").strip()
    if not user_text:
        return JSONResponse({"error": "Empty message"}, status_code=400)
    if not conversation:
        if not llm_enabled():
            return JSONResponse(
                {"error": "LLM disabled: SLAC_API_KEY required"},
                status_code=503,
            )
        client = OpenCodeClient()
        if not client.health_check():
            return JSONResponse(
                {"error": f"opencode server at {OPENCODE_URL} is not reachable"},
                status_code=503,
            )
        conversation = ConversationService(client)
    slack_bridge.post_user_message(user_text)
    result = conversation.handle_message(user_text)
    slack_bridge.post_llm_response(result.text)
    return {"response": result.text, "images": result.images}


TOOL_CATEGORIES = [
    ("Scan Data & Analysis",
     ["get_latest_scan", "list_scans", "read_scan", "get_active_counter",
      "get_scan_deadtime", "normalize_scan", "average_scans",
      "analyze_convergence", "analyze_efficiency"]),
    ("Plots", ["plot_scan", "plot_averaged_scans", "plot_data"]),
    ("Beamline Logs", ["get_latest_log_entries", "search_logs", "list_logs"]),
    ("Files & Macros", ["list_files", "read_file", "write_summary", "write_macro"]),
    ("SPEC Control", ["get_motor_config", "get_counter_config", "spec_command"]),
]


@app.get(f"{BASE_PATH}/api/tools")
async def get_tools():
    from tools import TOOL_DEFINITIONS, AUTONOMY_TOOL_CATEGORIES
    from tools.cli import REFERENCE_DOCS
    by_name = {
        t["function"]["name"]: t["function"]["description"] for t in TOOL_DEFINITIONS
    }
    categorized = []
    seen = set()
    for category, names in TOOL_CATEGORIES + AUTONOMY_TOOL_CATEGORIES:
        items = [{"name": n, "description": by_name[n]} for n in names if n in by_name]
        seen.update(i["name"] for i in items)
        if items:
            categorized.append({"category": category, "tools": items})
    leftover = [
        {"name": n, "description": d} for n, d in by_name.items() if n not in seen
    ]
    if leftover:
        categorized.append({"category": "Other", "tools": leftover})
    references = [
        {"name": name, "description": doc["description"]}
        for name, doc in REFERENCE_DOCS.items()
    ]
    return {"categories": categorized, "references": references}


@app.post(f"{BASE_PATH}/api/reset")
async def reset():
    global conversation
    if llm_enabled():
        client = OpenCodeClient()
        conversation = ConversationService(client)
    slack_bridge.reset_thread()
    return {"status": "reset"}


# ---- WebSocket -----------------------------------------------------------

@app.websocket(f"{BASE_PATH}/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_ws.add(ws)
    logger.info("WebSocket client connected (%d total)", len(connected_ws))
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        connected_ws.discard(ws)
        logger.info("WebSocket client disconnected (%d total)", len(connected_ws))


# ---- Entrypoint ----------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", str(PORT)))
    uvicorn.run(app, host="0.0.0.0", port=port)
