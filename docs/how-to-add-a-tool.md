# How to add a tool to the BeamtimeHero CLI

This guide is the recipe for landing a new tool in the autonomous-beamline tool catalog. It covers three flavors:

1. **SPEC-bound tools** — anything that injects a SPEC command (motor moves, scans, alignment macros).
2. **Non-SPEC tools** — anything that doesn't talk to SPEC or the orchestration DB (file I/O, analysis, camera, external HTTP).
3. **DB tools** — tools with `source: "autonomy_db"` in lineage that read/write the orchestration SQLite DB (experiment plan, budget, sample progress, guidance, interventions).

All three flavors use the same registration pattern (schema, handler, dispatch, lineage). The only differences are which imports the handler uses and how the auto-generated CLI routes the call.

## Architecture overview

The tool system spans two packages:

- **`beamtimehero_cli`** (upstream, editable install at `../beamtimehero_cli`) — generic, reusable tools: SPEC primitives, scan/log/data readers, motor moves (CAT-0..CAT-7, CAT-9). ~82 tools. Other projects consuming `beamtimehero_cli` benefit too.
- **`beamline_tools`** (this repo, `beamline_tools/tool_catalog/`) — autonomy-only tools: CAT-8 orchestration (plan edits, intervention requests, sample budgets, anything that imports `orchestration.*`).

At runtime, `beamline_tools/tool_catalog/__init__.py` concatenates upstream + autonomy definitions and dispatchers via `{**upstream, **autonomy}`. Autonomy keys win on collision.

The architecture has many layers because each layer enforces a different invariant — role gating, action logging, schema validation, mock outputs. Adding a tool means making a small append in each of those places.

After patching the files, you regenerate `tools_config.json` and the new tool auto-appears in `scripts/beamtimehero` (the LLM-facing CLI) and in `tool-tester` (the operator UI). You don't wire those manually.

---

## Where to put a new tool

| Tool type | Package | Schema file | Handler file | Lineage file |
|-----------|---------|-------------|-------------|--------------|
| Generic / reusable (SPEC primitives, data readers) | `beamtimehero_cli` | `beamtimehero_cli/.../definitions.py` | `beamtimehero_cli/.../tools_core.py` | `beamtimehero_cli/.../lineage.py` |
| Autonomy-only (orchestration, plan, camera) | `beamline_tools` | `beamline_tools/tool_catalog/definitions.py` | `beamline_tools/tool_catalog/tools.py` | `beamline_tools/tool_catalog/lineage.py` |

This guide focuses on the autonomy-side paths. Upstream follows the same pattern but the file paths live under `../beamtimehero_cli/src/beamtimehero_cli/tool_catalog/`.

---

## SPEC-bound tools (7 files + regenerate)

Use this flavor when your tool ultimately calls `audited_call(...)` to inject a SPEC command. Almost every alignment / scan / motor / macro wrapper is of this shape.

### Pre-flight: confirm the SPEC macro exists

Before writing any Python, find the macro definition under `/usr/local/lib/spec.d/`:

```bash
grep -rn "^def my_macro\b" /usr/local/lib/spec.d/*.mac
```

Read the macro itself. You need to know:
- What arguments it takes (positional, types).
- What it prints on completion (so you can write a parser and a mock output).
- How long it runs (sub-second / multi-second / multi-minute) — you'll set `timeout_s` accordingly.
- Any preconditions it asserts (refuses with a `p "..."; exit` line). Mirror those at the Python layer if possible.

If the macro doesn't exist yet, write it first.

### File 1 — CommandSpec (upstream `spec_cmd.py`)

Append a `CommandSpec` to the `_ACTION` dict (or `_READ` for read-only commands) in `beamtimehero_cli`'s `spec_control/spec_cmd.py`. The key is the command name used by `spec_cmd.call("<key>", ...)`:

```python
"mvpinhole": CommandSpec(
    "mvpinhole", "action",
    lambda a: "mvpinhole",                       # to_spec — render args into SPEC string
    lambda o, a: {"raw": o},                     # result_parser — pull structured data out
    timeout_s=60,
),
```

For commands with structured args:

```python
"measure_beam_size": CommandSpec(
    "measure_beam_size", "action",
    lambda a: f"measure_beam_size {a[0]} {a[1]}",
    lambda o, a: {"mode_x": int(a[0]), "mode_z": int(a[1]), "raw": o},
    timeout_s=600,
),
```

For motor-bearing commands (`umv`, `mv`, `dscan`, ...), set `needs_motor_allow=True` and `motor_arg_index=0`.

### File 2 — Agent-role allowlist (`beamline_tools/agent_roles.py`)

If the new command is a write-tool an agent role should be allowed to invoke, add it to that role's `spec_write_tools` frozenset in `beamline_tools/agent_roles.py`.

Each agent role (`blaligner`, `samplealigner`, `collector`, `surveyor`) has:
- `spec_write_tools` — frozenset of SPEC command names the role may call.
- `motors` — set of motor mnemonics the role may move.

```python
AGENT_ROLES = {
    "blaligner": {
        "spec_write_tools": frozenset({
            ...,
            "mvpinhole",   # ← add here
        }),
        "motors": {...},
    },
    ...
}
```

If your command moves a motor that isn't already on the relevant role's `motors` set, add it.

### File 3 — Schema (`beamline_tools/tool_catalog/definitions.py`)

Append a JSON-schema entry to `AUTONOMY_TOOL_DEFINITIONS`. Tool names are snake_case; the auto-generated CLI converts to kebab-case (`mv_pinhole` → `mv-pinhole`).

Every SPEC-write tool MUST have `justification` in `required` — the dispatcher rejects empty justifications, and the auto-generated CLI uses the presence of `justification` to route a tool into `spec-write` rather than `spec-read` or `tool`.

```python
{
    "type": "function",
    "function": {
        "name": "mv_pinhole",
        "description": "Move the sample stage so the diagnostic-tool pinhole is in the beam. ...",
        "parameters": {
            "type": "object",
            "properties": _J,                    # _J is the shared {justification: ...} fragment
            "required": ["justification"],
        },
    },
},
```

Also add the new tool name to the relevant `AUTONOMY_TOOL_CATEGORIES` row at the bottom of the file.

### File 4 — Handler + dispatch (`beamline_tools/tool_catalog/tools.py`)

Add a `t_<tool_name>` function, then register it in `_AUTONOMY_DISPATCH`. SPEC-mutating tools use `audited_call()` (not `spec_cmd.call()` directly) — it wraps the call with action logging, phase/experiment state, and the justification audit trail:

```python
def t_mv_pinhole(args: dict) -> tuple[str, list[str]]:
    j = (args.get("justification") or "").strip()
    res = audited_call("mvpinhole", [], justification=j)
    return _as_json(res), []
```

For structured args, convert each schema field to a positional string in the order your `to_spec` lambda expects:

```python
def t_measure_beam_size(args: dict) -> tuple[str, list[str]]:
    j = (args.get("justification") or "").strip()
    mode_x = "1" if bool(args.get("small_x", False)) else "0"
    mode_z = "1" if bool(args.get("small_z", False)) else "0"
    res = audited_call("measure_beam_size", [mode_x, mode_z], justification=j)
    return _as_json(res), []
```

Then add to the dispatch table near the bottom:

```python
_AUTONOMY_DISPATCH: dict[str, callable] = {
    ...
    "mv_pinhole": t_mv_pinhole,
    "measure_beam_size": t_measure_beam_size,
}
```

The final `DISPATCH` dict merges upstream + autonomy:

```python
DISPATCH: dict[str, callable] = {**_UPSTREAM_DISPATCH, **_AUTONOMY_DISPATCH}
```

For long-running one-shot macros (`align_beamline`, `auto_sample_align`), call `_refuse_rerun_if_already_done(...)` at the top of the `t_*` function.

### File 5 — Lineage (`beamline_tools/tool_catalog/lineage.py`)

Append metadata to `_AUTONOMY_LINEAGE`. This drives the `/tools` UI page and is also how the unit-test script identifies SPEC-bound tools (any entry with `spec_command != None` is expected to have a test case):

```python
"mv_pinhole": {
    "long_description": "Move the sample stage so the diagnostic-tool pinhole is in the beam. ...",
    "python_func": "audited_call('mvpinhole', [], justification)",
    "spec_command": "mvpinhole",                 # MUST be non-None for SPEC tools
    "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
    "source": "spec_session",
    "source_detail": "Defined in beam_diagnostics.mac via rdef.",
    "depends_on": [],
},
```

The `source` field is one of: `spec_session`, `spec_datafile`, `spec_logfile`, `spec_config`, `autonomy_db`, `filesystem`, `tool_chain`, `slack`, `camera`. SPEC-injecting tools should use `spec_session`.

### File 6 — Mock output (upstream `transport.py`)

Add a branch to `_MockScreen.inject` in `beamtimehero_cli`'s `spec_control/transport.py` so `SPEC_MOCK=1` runs don't hang. Match the prefix you'll see on the wire:

```python
if low.startswith("mvpinhole"):
    cls._positions["Sx"] = 0.0
    cls._positions["Sy"] = 0.0
    return "mvpinhole complete. Sx=0 Sy=0 Sz=0 Sr=0"
```

For long-running mock branches, `time.sleep(0.1)` so the orchestrator's "did this take a sensible amount of time?" heuristics aren't tripped by zero-elapsed dispatches.

### File 7 — Unit test (`scripts/unit_test_spec_tools.py`)

Add a `Case` to the relevant `CASES_*` list (group by phase). The test asserts that calling the tool function dispatches the exact SPEC string you expect:

```python
Case("mv_pinhole", {"justification": "test"},
     ["mvpinhole"], note="diagnostic pinhole into beam"),
```

If your tool wraps a SPEC macro that lives in `/usr/local/lib/spec.d/`, also add it to `KNOWN_MACROS` at the top of the file. SPEC built-ins go in `KNOWN_BUILTINS`.

### File 8 — Regenerate `tools_config.json`

```bash
SPEC_MOCK=1 venv/bin/python scripts/generate_tools_config.py
```

The generator merges new tools into the existing config, preserving user-edited fields (`enabled`, `simulated`, `working_live`, `comments`, `sample_output`). The catalog filter (`beamline_tools/tool_catalog/__init__.py:_load_enabled_set`) reads this file at import time — tools with `enabled=False` are silently dropped.

---

## Non-SPEC tools (4 files + regenerate)

Use this flavor for tools that don't inject a SPEC command — file I/O, analysis, camera snapshots, external HTTP calls.

### File 1 — Schema (`beamline_tools/tool_catalog/definitions.py`)

Append the schema to `AUTONOMY_TOOL_DEFINITIONS`. Don't include `justification` — its presence triggers `spec-write` routing.

```python
{
    "type": "function",
    "function": {
        "name": "capture_sample_image",
        "description": "Capture a low-resolution JPEG snapshot of the sample ...",
        "parameters": {
            "type": "object",
            "properties": {
                "quality": {"type": "integer", "default": 50, "description": "..."},
            },
            "required": [],
        },
    },
},
```

Also add it to `AUTONOMY_TOOL_CATEGORIES`.

### File 2 — Handler + dispatch (`beamline_tools/tool_catalog/tools.py`)

Add a `t_<tool_name>` function and register it in `_AUTONOMY_DISPATCH`. Non-SPEC tools don't call `audited_call()` — they implement logic directly:

```python
def t_capture_sample_image(args: dict) -> tuple[str, list[str]]:
    import base64
    import requests
    from beamline_tools.config import SAMPLE_CAM_HOST, SAMPLE_CAM_PORT, SPEC_MOCK

    if SPEC_MOCK:
        return _as_json({"ok": True, "mock": True,
                         "note": "Camera not available in mock mode"}), []

    quality = max(1, min(100, int(args.get("quality", 50))))
    url = f"http://{SAMPLE_CAM_HOST}:{SAMPLE_CAM_PORT}/snapshot.jpg"
    resp = requests.get(url, params={"resolution": "low", "quality": str(quality)}, timeout=10)
    resp.raise_for_status()
    img_b64 = base64.b64encode(resp.content).decode("ascii")
    return _as_json({"ok": True, "size_bytes": len(resp.content)}), [img_b64]
```

Then add to `_AUTONOMY_DISPATCH`:

```python
_AUTONOMY_DISPATCH: dict[str, callable] = {
    ...
    "capture_sample_image": t_capture_sample_image,
}
```

For tools that write files, **always**:
- Validate the filename against an allow-list regex (no path separators, no traversal, no hidden files).
- Resolve the target path and assert it stays inside the intended root via `Path.is_relative_to`.
- Refuse silent overwrites unless the caller explicitly opts in.

### File 3 — Lineage (`beamline_tools/tool_catalog/lineage.py`)

Same as for SPEC tools, but `spec_command` is `None`:

```python
"capture_sample_image": {
    "long_description": "...",
    "python_func": "requests.get(.../snapshot.jpg, params={resolution: low, quality: q})",
    "spec_command": None,
    "output": "JSON: {ok, resolution, quality, size_bytes} + inline JPEG image",
    "source": "camera",
    "source_detail": "HTTP GET to the RPi-Cam snapshot endpoint.",
    "depends_on": [],
},
```

`spec_command: None` with `source: "autonomy_db"` routes the tool to `beamtimehero db`. `spec_command: None` with any other source routes to `beamtimehero tool`.

### File 4 — Config (`beamline_tools/config.py`, only if needed)

If your tool needs new configuration (hosts, ports, directories), add constants with env-var overrides:

```python
SAMPLE_CAM_HOST = os.environ.get("SAMPLE_CAM_HOST", "192.168.150.93")
SAMPLE_CAM_PORT = int(os.environ.get("SAMPLE_CAM_PORT", "8080"))
```

### File 5 — Regenerate `tools_config.json`

Same as for SPEC tools — run the generator.

---

## DB tools (4 files + regenerate)

DB tools are structurally identical to non-SPEC tools. The only difference is the lineage `source` field:

- Set `source: "autonomy_db"` — this routes the tool to `beamtimehero db` in the auto-generated CLI.
- The handler typically imports from `orchestration.plan_store` or similar.

Follow the non-SPEC tool checklist, substituting `source: "autonomy_db"` in lineage.

---

## The executor (`beamline_tools/tool_catalog/executor.py`)

You do **not** need to edit `executor.py`. It's a thin adapter (~58 lines) that accepts either the new 3-arg form `execute_tool(tree, name, args)` or the legacy 2-arg form `execute_tool(name, args)` and looks up the handler in `DISPATCH`. No tool-specific logic lives there.

---

## Testing

**SPEC tools.** Run the unit test:

```bash
SPEC_MOCK=1 \
SPEC_EVAL_URL=http://127.0.0.1:1 \
AUTONOMOUS_DB_PATH=/tmp/spec_test.db \
BEAMLINE_TOOLS_DB_PATH=/tmp/spec_test.db \
ORCHESTRATION_DB_PATH=/tmp/spec_test.db \
venv/bin/python scripts/unit_test_spec_tools.py
```

Two pieces of context:

- **`SPEC_EVAL_URL=http://127.0.0.1:1`** disables the sandbox client by pointing it at an unreachable port. Without this, when the dev sandbox is healthy, `spec_cmd.dispatch` routes through it instead of `_MockScreen.inject` — and the recorder hooks `_MockScreen.inject`. Every test then reports `dispatch mismatch: got []` because the recorder never fires.
- **The `*_DB_PATH` overrides** isolate the test's SQLite from the live app's database.

**Non-SPEC tools.** Smoke-test via the auto-generated CLI:

```bash
SPEC_MOCK=1 venv/bin/python scripts/beamtimehero tool capture-sample-image --quality 50
```

Or directly:

```python
from beamline_tools.tool_catalog.executor import execute_tool
result, imgs = execute_tool("capture_sample_image", {"quality": 50})
print(result, len(imgs))
```

**Tool-tester UI.** No code change needed — `tool-tester/app.py` reads `tools_config.json` and auto-generates form inputs from each tool's schema. Just regenerate the config and refresh the page.

---

## Sequencing

When adding multiple related tools at once:

1. Make all the file edits.
2. Run `scripts/generate_tools_config.py` once at the end (not after every file).
3. Run `scripts/unit_test_spec_tools.py` to confirm dispatch parity (SPEC tools only).
4. Smoke-test the new tools through `scripts/beamtimehero` (auto-generated CLI).
5. Open `tool-tester` in the browser, confirm the new tools render.
6. Consider updating `context/` files if the tool is something an autonomous agent should know about.

---

## Common gotchas

- **The tool doesn't appear in `beamtimehero --help`.** You forgot to regenerate `tools_config.json`. The catalog filter drops anything not in the enabled-set.
- **Schema validation passes but the tool errors out at runtime.** Check that the SPEC-cmd key in `_ACTION` matches the string you pass to `audited_call(...)` / `spec_cmd.call(...)`. They have to be identical.
- **The dispatcher refuses with "command 'X' is only allowed for role(s): ..."** You didn't add the tool to the right agent role's `spec_write_tools` frozenset in `agent_roles.py`.
- **Mock-mode runs hang or 404.** You didn't add a `_MockScreen.inject` branch in upstream's `transport.py`. The fallthrough `return f"ok: {cmd}"` works for trivial commands, but anything that returns parsed structured data needs a tailored branch.
- **`_refuse_rerun_if_already_done` keeps firing in tests.** That helper checks `action_log` for the same command + experiment. Tests that share an experiment ID across cases will trip it. Use a fresh experiment per test, or skip the guard for development.

---

## Quick checklist

For a new SPEC-bound tool:

- [ ] Read the SPEC macro under `/usr/local/lib/spec.d/`
- [ ] Upstream `spec_cmd.py`: `CommandSpec` in `_ACTION` (or `_READ`)
- [ ] `agent_roles.py`: tool name in the relevant role's `spec_write_tools` frozenset (+ motor in `motors` if needed)
- [ ] `definitions.py`: schema in `AUTONOMY_TOOL_DEFINITIONS` + `AUTONOMY_TOOL_CATEGORIES` entry
- [ ] `tools.py`: `t_*` function using `audited_call()` + `_AUTONOMY_DISPATCH` entry
- [ ] `lineage.py`: metadata entry in `_AUTONOMY_LINEAGE` with non-None `spec_command`
- [ ] Upstream `transport.py`: `_MockScreen.inject` branch
- [ ] `unit_test_spec_tools.py`: `Case` + `KNOWN_MACROS` entry
- [ ] Run `scripts/generate_tools_config.py`
- [ ] Run `scripts/unit_test_spec_tools.py` (with the env vars above)
- [ ] Smoke-test through `scripts/beamtimehero spec-write <tool> --justification "..."`

For a new non-SPEC / DB tool:

- [ ] `definitions.py`: schema in `AUTONOMY_TOOL_DEFINITIONS` (no `justification`) + `AUTONOMY_TOOL_CATEGORIES` entry
- [ ] `tools.py`: `t_*` function + `_AUTONOMY_DISPATCH` entry (handle `SPEC_MOCK` if the tool calls external services)
- [ ] `lineage.py`: metadata entry in `_AUTONOMY_LINEAGE` with `spec_command: None` (use `source: "autonomy_db"` for DB tools)
- [ ] `config.py`: new constants if needed (with env-var overrides)
- [ ] Run `scripts/generate_tools_config.py`
- [ ] Smoke-test through `scripts/beamtimehero tool <name>` (or `beamtimehero db <name>` for DB tools)
