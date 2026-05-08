"""FastAPI application — UI layer.

Owns: static asset mounting, HTML page routes, WebSocket broadcast,
chat endpoint wrapper, tool catalog endpoint, Slack adapter.

All LLM / orchestrator / plan state goes through `orchestration.api`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from orchestration import api as orch_api
from orchestration.chat import (
    ChatRouter,
    archive_session,
    get_active_session_by_key,
    set_chat_router_singleton,
)
from orchestration.config import OPENCODE_URL, llm_enabled
from ui.adapters.slack_bridge import SlackBridge
from ui.config import BASE_PATH, PORT, PROJECT_ROOT, STATIC_DIR
from ui.server.routers import (
    agents_api,
    config_api,
    dashboard_api,
    insight_api,
    orchestrator_api,
    phase_runner_api,
    plan_api,
    safety_switches_api,
    sample_holders_api,
    slack_status_api,
    spec_log_api,
    tool_plots_api,
    viewer_api,
)


# Set at startup so the manual /api/slack/status endpoint can post
# directly when the orchestrator isn't running.
_slack_bridge_for_status = None


_LOG_DIR = PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FMT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_log_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "server.log", maxBytes=5 * 1024 * 1024, backupCount=5,
)
_log_file_handler.setFormatter(logging.Formatter(_LOG_FMT))
logging.basicConfig(
    format=_LOG_FMT, level=logging.INFO,
    handlers=[logging.StreamHandler(), _log_file_handler],
)
logger = logging.getLogger(__name__)

_NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _page(path: Path) -> FileResponse:
    return FileResponse(path, media_type="text/html", headers=_NOCACHE)


TOOL_CATEGORIES = [
    ("Scan Data & Analysis",
     ["get_latest_scan", "list_scans", "read_scan", "get_active_counter",
      "get_scan_deadtime", "normalize_scan", "average_scans",
      "analyze_convergence", "analyze_efficiency"]),
    ("Plots", ["plot_scan", "plot_averaged_scans", "plot_data"]),
    ("Beamline Logs", ["get_latest_log_entries", "search_logs", "list_logs"]),
    ("Files & Macros", ["list_files", "read_file", "write_summary", "write_macro"]),
    ("SPEC Control", ["get_motor_config", "get_counter_config"]),
]


def create_app() -> FastAPI:
    """Build the FastAPI app. Orchestration wires itself in via lifespan."""
    slack_bridge = SlackBridge()
    # Expose the bridge via a module-level reference so the manual
    # /api/slack/status endpoint can fall back to it when the orchestrator
    # is not running.
    global _slack_bridge_for_status
    _slack_bridge_for_status = slack_bridge
    connected_ws: set[WebSocket] = set()
    event_loop_holder: dict = {"loop": None}

    async def broadcast_ws(message: dict) -> None:
        payload = json.dumps(message, default=str)
        disconnected = set()
        for ws in connected_ws:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        connected_ws.difference_update(disconnected)

    def broadcast(msg: dict) -> None:
        loop = event_loop_holder["loop"]
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(broadcast_ws(msg), loop)

    # -- lifespan combines UI + orchestration ---------------------------

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        event_loop_holder["loop"] = asyncio.get_running_loop()
        # Tell orchestration how to emit events + post status updates.
        orch_api.set_event_emitter(broadcast)
        orch_api.set_slack_status_post(lambda text: slack_bridge.post_status_update(text))
        orch_api.set_slack_post_steering_reply(slack_bridge.post_steering_reply)
        orch_api.set_insight_record_turn(insight_api.record_turn)

        # Wire Slack bridge → orchestration routing callbacks.
        def _on_setdir(dir_name: str) -> str:
            return orch_api.on_setdir(dir_name)

        def _on_resolve(intervention_id: str, status: str, staff_name: str):
            orch_api.on_intervention_resolve(
                intervention_id, status, staff_name, event_loop_holder["loop"],
            )

        slack_bridge.set_steering_callback(orch_api.on_steering_message)
        slack_bridge.set_chat_callback(orch_api.on_chat_message)
        slack_bridge.set_setdir_callback(_on_setdir)
        slack_bridge.set_intervention_resolve_callback(_on_resolve)
        slack_bridge.start()

        # Wire the chat router. Slack chat / DM / UI chat box all funnel
        # through ChatRouter.handle_inbound, which spawns chat-claude.sh
        # subprocesses per ChatSession and posts the agent's reply back
        # to Slack and over the WebSocket to the UI.
        chat_router = ChatRouter(
            slack_post_chat_reply=slack_bridge.post_chat_reply,
            slack_post_chat_root=slack_bridge.post_chat_root,
            ws_emit=broadcast,
        )
        set_chat_router_singleton(chat_router)
        orch_api.set_chat_handler(chat_router.handle_inbound)

        # Run orchestration's own lifespan (DB init, Orchestrator wiring).
        async with orch_api.lifespan(app):
            yield

    app = FastAPI(title="Autonomous Beamline Agent", lifespan=lifespan)

    # -- static + routers -----------------------------------------------

    app.mount(
        f"{BASE_PATH}/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )
    app.include_router(agents_api.router)
    app.include_router(config_api.router)
    app.include_router(dashboard_api.router)
    app.include_router(orchestrator_api.router)
    app.include_router(phase_runner_api.router)
    app.include_router(plan_api.router)
    app.include_router(safety_switches_api.router)
    app.include_router(spec_log_api.router)
    app.include_router(tool_plots_api.router)
    app.include_router(insight_api.router)
    app.include_router(sample_holders_api.router)
    app.include_router(slack_status_api.router)
    app.include_router(viewer_api.router)

    # -- health ---------------------------------------------------------

    @app.get(f"{BASE_PATH}/health")
    async def health():
        try:
            from beamline_tools import config as bl_config
            scan_dir = str(bl_config.BL_SCAN_DIR)
        except Exception:
            scan_dir = None
        return {
            "status": "ok",
            "phase": orch_api.current_experiment_id() and orch_api.orchestrator_snapshot().get("phase"),
            "opencode_reachable": orch_api.agent_reachable(),
            "orchestrator_initialized": orch_api.orchestrator_snapshot().get("initialized", False),
            "bl_scan_dir": scan_dir,
        }

    # -- page routes ----------------------------------------------------

    async def _index_page():
        return _page(STATIC_DIR / "dashboard" / "index.html")

    if BASE_PATH:
        app.get(BASE_PATH)(_index_page)
        app.get(f"{BASE_PATH}/")(_index_page)
    else:
        app.get("/")(_index_page)

    @app.get(f"{BASE_PATH}/config")
    async def config_page():
        return _page(STATIC_DIR / "config" / "index.html")

    @app.get(f"{BASE_PATH}/dashboard")
    async def dashboard_page():
        return _page(STATIC_DIR / "dashboard" / "index.html")

    @app.get(f"{BASE_PATH}/phase")
    async def phase_page():
        return _page(STATIC_DIR / "dashboard" / "phase.html")

    @app.get(f"{BASE_PATH}/sample_planning")
    async def sample_planning_page():
        return _page(STATIC_DIR / "sample_planning" / "index.html")

    @app.get(f"{BASE_PATH}/sample_holders")
    async def sample_holders_page():
        return _page(STATIC_DIR / "sample_holders" / "index.html")

    @app.get(f"{BASE_PATH}/viewer")
    async def viewer_page():
        return _page(STATIC_DIR / "viewer" / "index.html")

    @app.get(f"{BASE_PATH}/tools")
    async def tools_page():
        return _page(STATIC_DIR / "tools" / "index.html")

    @app.get(f"{BASE_PATH}/insight")
    async def insight_page():
        return _page(STATIC_DIR / "insight" / "index.html")

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

    # -- chat endpoint --------------------------------------------------
    #
    # The new flow: POST /api/chat enqueues the inbound through the
    # ChatRouter, which spawns a chat-claude.sh agent for the session.
    # The actual reply arrives asynchronously over the WebSocket as a
    # `chat_reply` event. The endpoint just returns a queued/started
    # status immediately.

    @app.post(f"{BASE_PATH}/api/chat")
    async def chat(payload: dict):
        user_text = (payload.get("message") or "").strip()
        if not user_text:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        ui_session_id = payload.get("ui_session_id")
        if not ui_session_id:
            # Mint one for the client and tell it to remember (the
            # frontend can persist this in localStorage and re-send).
            ui_session_id = uuid.uuid4().hex[:12]

        from orchestration.chat import chat_router_singleton
        router = chat_router_singleton()
        if router is None:
            return JSONResponse(
                {"error": "Chat router not initialized"}, status_code=503,
            )

        # Run on a worker thread — handle_inbound does sync DB + spawn().
        result = await asyncio.to_thread(
            router.handle_inbound,
            text=user_text,
            author=payload.get("author") or "ui-user",
            channel=None,
            thread_ts=None,
            source="ui",
            ui_session_id=ui_session_id,
        )
        return {
            "queued": True,
            "ui_session_id": ui_session_id,
            "session_id": result.get("session_id"),
            "thread_key": result.get("thread_key"),
        }

    @app.post(f"{BASE_PATH}/api/chat/clear")
    async def chat_clear(payload: dict):
        """Archive the current UI chat session and return a fresh ui_session_id.

        The client is expected to replace its stored ui_session_id with
        the returned value — subsequent messages start a brand-new session.
        """
        ui_session_id = (payload.get("ui_session_id") or "").strip()
        if ui_session_id:
            thread_key = f"ui:{ui_session_id}"
            existing = await asyncio.to_thread(get_active_session_by_key, thread_key)
            if existing is not None:
                await asyncio.to_thread(archive_session, existing["id"])
        return {"ok": True, "new_ui_session_id": uuid.uuid4().hex[:12]}

    # -- tool catalog endpoint ------------------------------------------

    @app.get(f"{BASE_PATH}/api/tools")
    async def get_tools():
        # Import orchestration first so its CAT-8 plan tools register.
        import orchestration  # noqa: F401
        from beamline_tools.tool_catalog import (
            AUTONOMY_TOOL_CATEGORIES,
            TOOL_DEFINITIONS,
        )
        from beamline_tools.tool_catalog.cli import REFERENCE_DOCS
        from beamline_tools.tool_catalog.lineage import build_detailed_tool

        by_def = {t["function"]["name"]: t for t in TOOL_DEFINITIONS}
        categorized: list[dict] = []
        seen: set[str] = set()
        for category, names in TOOL_CATEGORIES + AUTONOMY_TOOL_CATEGORIES:
            items = [
                build_detailed_tool(by_def[n], category)
                for n in names if n in by_def
            ]
            seen.update(i["name"] for i in items)
            if items:
                categorized.append({"category": category, "tools": items})
        leftover = [
            build_detailed_tool(tdef, "Other")
            for n, tdef in by_def.items() if n not in seen
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
        orch_api.reset_conversation()
        # Slack thread state no longer lives in the bridge; nothing to reset here.
        return {"status": "reset"}

    # -- WebSocket ------------------------------------------------------

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

    return app
