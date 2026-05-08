"""Tool plots tail API.

Surfaces the most recent PNG written by tool dispatchers under
`data/tool_plots/` so the dashboard can show a live "Agent Plots" tile.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ui.config import PROJECT_ROOT

router = APIRouter(prefix="/api/tool_plots", tags=["tool_plots"])

_PLOT_DIR = PROJECT_ROOT / "data" / "tool_plots"


def _latest_png() -> Path | None:
    if not _PLOT_DIR.exists():
        return None
    pngs = list(_PLOT_DIR.glob("*.png"))
    if not pngs:
        return None
    pngs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pngs[0]


@router.get("/latest")
async def latest():
    """Return metadata for the most-recent plot, or {filename: null} if none."""
    p = _latest_png()
    if p is None:
        return {"filename": None, "mtime": 0}
    return {"filename": p.name, "mtime": p.stat().st_mtime}


@router.get("/file/{filename}")
async def file(filename: str):
    """Serve a single plot PNG. Filename is restricted to the plot dir
    (no traversal) and must end with .png."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    if not filename.lower().endswith(".png"):
        raise HTTPException(400, "only .png files are served")
    target = _PLOT_DIR / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "plot not found")
    # Resolve to make sure we're still inside the plot dir.
    if _PLOT_DIR.resolve() not in target.resolve().parents:
        raise HTTPException(400, "invalid filename")
    return FileResponse(target, media_type="image/png")
