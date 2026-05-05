#!/usr/bin/env python3
"""Standalone tool-tester web app.

Run with: python tool-tester/app.py
Serves at: http://localhost:8418
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
CONFIG_PATH = ROOT / "beamline_tools" / "tools_config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
BEAMTIMEHERO = ROOT / "scripts" / "beamtimehero"

PORT = 8418
SPEC_MOCK = os.environ.get("SPEC_MOCK", "1") == "1"

ALL_PHASES = [
    "setup", "beamline_alignment", "xes_alignment",
    "sample_alignment", "collection", "complete",
]

app = FastAPI(title="BeamtimeHero Tool Tester")
_lock = threading.Lock()


def _read_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _write_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# -- API endpoints ----------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return JSONResponse(_read_config())


class ToolUpdate(BaseModel):
    enabled: bool | None = None
    simulated: bool | None = None
    working_live: bool | None = None
    comments: str | None = None
    sample_input: dict | None = None
    sample_output: str | None = None


@app.put("/api/config/{tool_name}")
async def update_tool(tool_name: str, update: ToolUpdate):
    with _lock:
        data = _read_config()
        tool = next((t for t in data["tools"] if t["name"] == tool_name), None)
        if not tool:
            raise HTTPException(404, f"Tool '{tool_name}' not found")
        for field, value in update.model_dump(exclude_none=True).items():
            tool[field] = value
        _write_config(data)
    return {"ok": True, "tool": tool}


@app.get("/api/mock-status")
async def mock_status():
    return {"mock": SPEC_MOCK, "phases": ALL_PHASES}


class TestRequest(BaseModel):
    args: dict = {}
    phase_override: str | None = None


@app.post("/api/test/{tool_name}")
async def test_tool(tool_name: str, req: TestRequest):
    data = _read_config()
    tool = next((t for t in data["tools"] if t["name"] == tool_name), None)
    if not tool:
        raise HTTPException(404, f"Tool '{tool_name}' not found")

    cli_path = tool["cli_path"]
    cli_name = tool_name.replace("_", "-")

    cmd = [sys.executable, str(BEAMTIMEHERO)]
    if cli_path == "ref":
        cmd += ["ref", tool_name]
    else:
        cmd += [cli_path, cli_name]
        for key, value in req.args.items():
            flag = f"--{key.replace('_', '-')}"
            if isinstance(value, bool):
                cmd += [flag, str(value).lower()]
            elif isinstance(value, (list, dict)):
                cmd += [flag, json.dumps(value)]
            else:
                cmd += [flag, str(value)]

    env = None
    if SPEC_MOCK and req.phase_override and req.phase_override in ALL_PHASES:
        env = {**os.environ, "SPEC_PHASE_OVERRIDE": req.phase_override}

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            env=env,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": duration_ms,
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Command timed out after 120 seconds",
            "duration_ms": 120000,
            "command": " ".join(cmd),
        }


# -- Static files + page route ---------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
