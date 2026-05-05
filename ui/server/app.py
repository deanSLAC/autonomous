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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from orchestration import api as orch_api
from orchestration.config import OPENCODE_URL, llm_enabled
from ui.adapters.slack_bridge import SlackBridge
from ui.config import BASE_PATH, PORT, PROJECT_ROOT, STATIC_DIR
from ui.server.routers import (
    config_api,
    dashboard_api,
    insight_api,
    orchestrator_api,
    plan_api,
    sample_holders_api,
    viewer_api,
)


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
        orch_api.set_insight_record_turn(insight_api.record_turn)

        # Wire Slack bridge → orchestration routing callbacks.
        slack_bridge.set_staff_callback(orch_api.on_staff_message)

        def _on_llm_thread_reply(text: str, staff_name: str):
            result = orch_api.on_llm_thread_reply(text, staff_name)
            if result:
                slack_bridge.post_llm_response(result["text"])

        slack_bridge.set_llm_thread_callback(_on_llm_thread_reply)

        def _on_dm(text: str, staff_name: str, dm_thread_key: str):
            reply = orch_api.on_dm_message(text, staff_name, dm_thread_key)
            if reply:
                channel, thread_ts = dm_thread_key.split(":", 1)
                slack_bridge.post_dm_reply(channel, thread_ts, reply)

        slack_bridge.set_dm_callback(_on_dm)

        def _on_setdir(dir_name: str) -> str:
            msg = orch_api.on_setdir(dir_name)
            slack_bridge.reset_thread()
            return msg

        slack_bridge.set_setdir_callback(_on_setdir)

        def _on_resolve(intervention_id: str, status: str, staff_name: str):
            orch_api.on_intervention_resolve(
                intervention_id, status, staff_name, event_loop_holder["loop"],
            )

        slack_bridge.set_intervention_resolve_callback(_on_resolve)
        slack_bridge.start()

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
    app.include_router(config_api.router)
    app.include_router(dashboard_api.router)
    app.include_router(orchestrator_api.router)
    app.include_router(plan_api.router)
    app.include_router(insight_api.router)
    app.include_router(sample_holders_api.router)
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

    @app.post(f"{BASE_PATH}/api/chat")
    async def chat(payload: dict):
        user_text = (payload.get("message") or "").strip()
        if not user_text:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        page = payload.get("page")
        page_context = payload.get("page_context")
        if not isinstance(page_context, dict):
            page_context = None

        slack_bridge.post_user_message(user_text)
        try:
            result = orch_api.handle_chat(
                user_text,
                experiment_id=payload.get("experiment_id"),
                page=page,
                page_context=page_context,
            )
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        slack_bridge.post_llm_response(result["response"])
        return result

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
        slack_bridge.reset_thread()
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
