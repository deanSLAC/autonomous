"""Manual Slack status post endpoint."""
from fastapi import APIRouter, HTTPException

from orchestration.planner.loop import get_orchestrator

router = APIRouter(prefix="/api/slack", tags=["slack"])


@router.post("/status")
async def post_status(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    thread_ts = payload.get("thread_ts")
    orch = get_orchestrator()
    if orch is None:
        # No orchestrator running — fall back to the slack bridge that
        # ui.server.app stashed at startup.
        from ui.server import app as ui_app
        bridge = getattr(ui_app, "_slack_bridge_for_status", None)
        if bridge is None:
            raise HTTPException(503, "Slack bridge not configured")
        try:
            bridge.post_status_update(text, thread_ts=thread_ts)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"slack post failed: {e}") from e
    else:
        orch.slack_status_post(text)
    return {"ok": True, "text_len": len(text)}
