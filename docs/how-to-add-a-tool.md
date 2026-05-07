# How to add a tool to the BeamtimeHero CLI

This guide is the recipe for landing a new tool in the autonomous-beamline tool catalog. It covers three flavors:

1. **SPEC-bound tools** — anything that injects a SPEC command (motor moves, scans, alignment macros). Eight files to touch.
2. **Non-SPEC tools** — anything that doesn't talk to SPEC or the orchestration DB (file I/O, analysis). Five files.
3. **DB tools** — tools with `source: "autonomy_db"` in lineage that read/write the orchestration SQLite DB (experiment plan, budget, sample progress, guidance, interventions). Auto-route to `beamtimehero db`. Same five files as non-SPEC tools; the only difference is the lineage `source` field.

The architecture has many layers because each layer enforces a different invariant — phase gating, action logging, schema validation, mock outputs. Adding a tool means making a small append in each of those places, not editing one big switch statement.

After patching the files, you regenerate `tools_config.json` and the new tool auto-appears in `scripts/beamtimehero` (the LLM-facing CLI) and in `tool-tester` (the operator UI). You don't wire those manually.

---

## SPEC-bound tools (8 files)

Use this flavor when your tool ultimately calls `spec_cmd.call(...)` to inject a SPEC command. Almost every alignment / scan / motor / macro wrapper is of this shape.

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

If the macro doesn't exist yet, write it first. Adding a CLI surface to a phantom macro just produces a runtime error.

### File 1 — `beamline_tools/spec_control/spec_cmd.py`

Append a `CommandSpec` to the `_ACTION` dict (or `_READ` for read-only commands). The key is the command name used by `spec_cmd.call("<key>", ...)`. Conventionally this matches the SPEC macro token verbatim (`mvpinhole`, `peak_mono_pitch`, `safely_remove_filters`).

```python
"mvpinhole": CommandSpec(
    "mvpinhole", "action",
    lambda a: "mvpinhole",                       # to_spec — render args into SPEC string
    lambda o, a: {"raw": o},                     # result_parser — pull structured data out
    timeout_s=60,                                # how long we'll wait for completion
),
```

For commands with structured args, the renderer formats them and the parser converts the `args` list back into named fields:

```python
"measure_beam_size": CommandSpec(
    "measure_beam_size", "action",
    lambda a: f"measure_beam_size {a[0]} {a[1]}",
    lambda o, a: {"mode_x": int(a[0]), "mode_z": int(a[1]), "raw": o},
    timeout_s=600,
),
```

For motor-bearing commands (`umv`, `mv`, `dscan`, ...), set `needs_motor_allow=True` and `motor_arg_index=0` so the dispatcher checks the motor against the phase's motor allowlist.

### File 2 — `beamline_tools/spec_control/phase_allowlist.py`

Add the SPEC command name to `PROCEDURAL_PHASE` with the set of phases where it's allowed:

```python
PROCEDURAL_PHASE = {
    ...
    "mvpinhole": {PHASE_BL_ALIGN},
    "mvplastic": {PHASE_BL_ALIGN, PHASE_XES_ALIGN},
}
```

If the command is allowed in every running phase (motor primitives, shutter, ct), put it in `PROCEDURAL_ANY_PHASE` instead.

If your command moves a motor that isn't already on the relevant phase's `_*_MOTORS` set, add it. The dispatcher refuses moves to motors that aren't on the active phase's allowlist.

### File 3 — `beamline_tools/tool_catalog/autonomy_definitions.py`

Append a JSON-schema entry to `AUTONOMY_TOOL_DEFINITIONS`. This is the schema the LLM sees. Tool names are snake_case; the auto-generated CLI converts to kebab-case (`mv_pinhole` → `mv-pinhole`).

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

For structured args, expand `properties` with the schema fields:

```python
"properties": {
    **_J,
    "small_x": {"type": "boolean", "default": False, "description": "..."},
    "small_z": {"type": "boolean", "default": False, "description": "..."},
},
```

Also add the new tool name to the relevant `AUTONOMY_TOOL_CATEGORIES` row at the bottom of the file (this drives the sidebar grouping in the UI).

### File 4 — `beamline_tools/tool_catalog/autonomy_tools.py`

Add a `t_<tool_name>` wrapper, then register it in `AUTONOMY_DISPATCH`. The wrapper is the bridge between LLM-shaped args and the spec_cmd renderer:

```python
def t_mv_pinhole(args: dict) -> tuple[str, list[str]]:
    j = (args.get("justification") or "").strip()
    res = spec_cmd.call("mvpinhole", [], justification=j)
    return _as_json(res), []
```

For structured args, convert each schema field to a positional string in the order your `to_spec` lambda expects:

```python
def t_measure_beam_size(args: dict) -> tuple[str, list[str]]:
    j = (args.get("justification") or "").strip()
    mode_x = "1" if bool(args.get("small_x", False)) else "0"
    mode_z = "1" if bool(args.get("small_z", False)) else "0"
    res = spec_cmd.call("measure_beam_size", [mode_x, mode_z], justification=j)
    return _as_json(res), []
```

Then add to the dispatch table near the bottom:

```python
AUTONOMY_DISPATCH = {
    ...
    "mv_pinhole": t_mv_pinhole,
    "measure_beam_size": t_measure_beam_size,
}
```

For long-running one-shot macros (`align_beamline`, `auto_sample_align`), call `_refuse_rerun_if_already_done(...)` at the top of the `t_*` function — see the existing pattern.

### File 5 — `beamline_tools/tool_catalog/lineage.py`

Append metadata to `TOOL_LINEAGE`. This drives the `/tools` UI page and is also the way the unit-test script identifies SPEC-bound tools (any entry with `spec_command != None` is expected to have a test case).

```python
"mv_pinhole": {
    "long_description": "Move the sample stage so the diagnostic-tool pinhole is in the beam. ...",
    "python_func": "spec_cmd.call('mvpinhole', [], justification)",
    "spec_command": "mvpinhole",                 # MUST be non-None for SPEC tools
    "output": "JSON: {ok, kind, action_id, result: {raw, elapsed_s}, elapsed_s}",
    "source": "spec_session",
    "source_detail": "Defined in beam_diagnostics.mac via rdef.",
    "depends_on": [],
},
```

The `source` field is one of: `spec_session`, `spec_datafile`, `spec_logfile`, `spec_config`, `autonomy_db`, `filesystem`, `tool_chain`, `slack`. SPEC-injecting tools should use `spec_session`.

### File 6 — `beamline_tools/spec_control/transport.py`

Add a branch to `_MockScreen.inject` that returns synthetic output for the new SPEC string, so `SPEC_MOCK=1` runs (used by tests, the dashboard, and laptop development) don't hang or error. Match the prefix you'll see on the wire:

```python
if low.startswith("mvpinhole"):
    cls._positions["Sx"] = 0.0
    cls._positions["Sy"] = 0.0
    cls._positions["Sz"] = 0.0
    cls._positions["Sr"] = 0.0
    return "mvpinhole complete. Sx=0 Sy=0 Sz=0 Sr=0"
```

For long-running mock branches, `time.sleep(0.1)` so the orchestrator's "did this take a sensible amount of time?" heuristics don't get tripped by zero-elapsed dispatches:

```python
if low.startswith("measure_beam_size"):
    time.sleep(0.1)
    return "measure_beam_size complete. beamsize_x=0.35 beamsize_z=0.12 mm"
```

If your mock should mutate `cls._positions` to keep `wa` / `wm` honest, do so.

### File 7 — `scripts/unit_test_spec_tools.py`

Add a `Case` to the relevant `CASES_*` list (group by phase). The test asserts that calling the tool function dispatches the exact SPEC string you expect:

```python
Case("mv_pinhole", {"justification": "test"},
     ["mvpinhole"], note="diagnostic pinhole into beam"),
```

For tools that fan out to multiple SPEC dispatches, list them in order:

```python
Case("...",
     {"justification": "test"},
     ["plotselect I1", "vvv", "peak"],
     note="combined diagnostic + analysis"),
```

If your tool wraps a SPEC macro that lives in `/usr/local/lib/spec.d/`, also add it to `KNOWN_MACROS` at the top of the file with its source path so the macro-existence audit doesn't flag it as missing. SPEC built-ins (`p`, `cen`, `peak`, `plotselect`) go in `KNOWN_BUILTINS` instead.

### File 8 — `beamline_tools/tools_config.json` (auto-generated)

This file is regenerated by `scripts/generate_tools_config.py`. Do **not** hand-edit. After making the changes above, run:

```bash
SPEC_MOCK=1 venv/bin/python scripts/generate_tools_config.py
```

The generator merges new tools into the existing config, preserving user-edited fields (`enabled`, `simulated`, `working_live`, `comments`, `sample_output`).

The catalog filter (`beamline_tools/tool_catalog/__init__.py:_load_enabled_set`) reads this file at import time — tools with `enabled=False` are silently dropped. Until you regenerate, your new tool is *defined* but won't appear in the auto-generated CLI or tool-tester.

---

## Non-SPEC tools (5 files)

Use this flavor for tools that don't inject a SPEC command — file I/O, analysis on already-collected data, plan saving, status posting. The shape is `save_plan`, `analyze_convergence`, `plot_scan`, `write_summary`.

### File 1 — `beamline_tools/tool_catalog/definitions.py`

Append the schema. Non-SPEC tools live here, **not** in `autonomy_definitions.py`. Don't include `justification` — its presence triggers `spec-write` routing.

```python
{
    "type": "function",
    "function": {
        "name": "save_plan",
        "description": "Save a markdown plan to the project's plans/ directory. ...",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "..."},
                "content": {"type": "string", "description": "..."},
                "overwrite": {"type": "boolean", "default": False, "description": "..."},
            },
            "required": ["filename", "content"],
        },
    },
},
```

### File 2 — `beamline_tools/tool_catalog/executor.py`

Add an `elif name == "<tool_name>":` branch inside `execute_tool()`. This is the actual implementation. Validate inputs, do the work, return `(json_string, [])`.

```python
elif name == "save_plan":
    import re as _re
    from beamline_tools.config import PLANS_DIR
    filename = (arguments.get("filename") or "").strip()
    content = arguments.get("content") or ""
    overwrite = bool(arguments.get("overwrite", False))
    if not _re.match(r"^[A-Za-z0-9_\-.]+\.md$", filename) or filename.startswith("."):
        return json.dumps({"ok": False, "error": "..."}), images_b64
    target = (PLANS_DIR / filename).resolve()
    try:
        target.relative_to(PLANS_DIR.resolve())
    except ValueError:
        return json.dumps({"ok": False, "error": "..."}), images_b64
    existed = target.exists()
    if existed and not overwrite:
        return json.dumps({"ok": False, "error": "..."}), images_b64
    target.write_text(content, encoding="utf-8")
    return json.dumps({"ok": True, "path": str(target), "bytes": ...}), images_b64
```

For tools that write files, **always**:
- Validate the filename against an allow-list regex (no path separators, no traversal, no hidden files).
- Resolve the target path and assert it stays inside the intended root via `Path.is_relative_to` (or the `try/except ValueError` form for Python < 3.9 compat).
- Refuse silent overwrites unless the caller explicitly opts in.

### File 3 — `beamline_tools/tool_catalog/lineage.py`

Same as for SPEC tools, but `spec_command` is `None`:

```python
"save_plan": {
    "long_description": "...",
    "python_func": "PLANS_DIR.joinpath(filename).write_text(content)  (with regex + path-confinement checks)",
    "spec_command": None,
    "output": "JSON: {ok, path, bytes, overwrote}",
    "source": "filesystem",                      # not spec_session
    "source_detail": "Writes into PLANS_DIR (./plans/ under the project root).",
    "depends_on": [],
},
```

`spec_command: None` with `source: "autonomy_db"` routes the tool to `beamtimehero db`. `spec_command: None` with any other source routes to `beamtimehero tool`.

### File 4 — `beamline_tools/config.py` (only if you need a new directory)

If your tool reads or writes a directory that isn't already exposed, add a constant:

```python
PLANS_DIR = PROJECT_ROOT / "plans"
PLANS_DIR.mkdir(exist_ok=True)
```

Then import that constant in `executor.py`.

### File 5 — `beamline_tools/tools_config.json` (auto-generated)

Same as before — run the generator after the rest of your edits.

### Don't bother with — `beamline_tools/tool_catalog/cli.py`

This file's `run_cli` function is **legacy / unused** as of 2026-05. The actual CLI is `scripts/beamtimehero`, which auto-generates argparse subparsers from `TOOL_DEFINITIONS`. Adding a subparser to `cli.py` is a no-op (its only live consumer is `REFERENCE_DOCS`, which we still import from there). New tools should not need a `cli.py` edit — and if you do edit it for consistency, no caller exercises that path.

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

- **`SPEC_EVAL_URL=http://127.0.0.1:1`** disables the sandbox client by pointing it at an unreachable port. Without this, when the dev sandbox is healthy, `spec_cmd.dispatch` routes through it instead of `_MockScreen.inject` — and the recorder hooks `_MockScreen.inject`. Every test then reports `dispatch mismatch: got []` because the recorder never fires. This is a quirk of the test infra: when the sandbox is up, you must point `SPEC_EVAL_URL` at a dead address to force the dispatcher onto the path the recorder watches.
- **The `*_DB_PATH` overrides** isolate the test's SQLite from the live app's database, which would otherwise produce `disk I/O error` from concurrent writes.

The script exits 0 on success and prints a per-tool PASS/FAIL table plus a macro-existence audit. Aim for `Total checks: N/N passed` and `Missing macros: 0` (the audit will tolerate a few known-missing-element-specific macros like `Fe_cee`).

**Non-SPEC tools.** No formal harness yet; smoke-test directly:

```python
from beamline_tools.tool_catalog.executor import execute_tool
result, _ = execute_tool("save_plan", {"filename": "test.md", "content": "..."})
print(result)
```

Or via the auto-generated CLI:

```bash
SPEC_MOCK=1 venv/bin/python scripts/beamtimehero tool save-plan --filename test.md --content "..."
```

For tools with adversarial-input concerns (file writes, anything that takes a path), test the rejection cases explicitly: traversal, missing extension, hidden files, overwrite collisions.

**Tool-tester UI.** No code change needed — `tool-tester/app.py` reads `tools_config.json` and `static/tool-tester.js` auto-generates form inputs from each tool's `sample_input` schema. Just regenerate the config and refresh the page.

---

## Sequencing

When adding multiple related tools at once, the order is:

1. Make all the file edits.
2. Run `scripts/generate_tools_config.py` once at the end (not after every file).
3. Run `scripts/unit_test_spec_tools.py` to confirm dispatch parity.
4. Smoke-test the new tools through `scripts/beamtimehero` (auto-generated CLI).
5. Open `tool-tester` in the browser, confirm the new tools render.
6. Update `context/beamtimehero_context.md` if the tool is something the autonomous agent should know about.

---

## Common gotchas

- **The tool doesn't appear in `beamtimehero --help`.** You forgot to regenerate `tools_config.json`. The catalog filter drops anything not in the enabled-set.
- **Schema validation passes but the tool errors out at runtime.** Check that the SPEC-cmd key in `_ACTION` matches the string you pass to `spec_cmd.call(...)`. They have to be identical.
- **The dispatcher refuses with "command 'X' is only allowed in phase(s): ..."** even though you listed it in `PROCEDURAL_PHASE`. Check that the active phase (set via `spec_cmd.set_phase(...)`) matches one of the phases in the set.
- **Mock-mode runs hang or 404.** You didn't add a `_MockScreen.inject` branch. The fallthrough `return f"ok: {cmd}"` works for trivial commands, but anything that returns parsed structured data (`mode_x`, `beamsize_x`, etc.) needs a tailored branch.
- **`_refuse_rerun_if_already_done` keeps firing in tests.** That helper checks `action_log` for the same command + experiment. Tests that share an experiment ID across cases will trip it. Use a fresh experiment per test, or skip the guard for development.

---

## Quick checklist

For a new SPEC-bound tool:

- [ ] Read the SPEC macro under `/usr/local/lib/spec.d/`
- [ ] `spec_cmd.py`: `CommandSpec` in `_ACTION` (or `_READ`)
- [ ] `phase_allowlist.py`: entry in `PROCEDURAL_PHASE` (or `PROCEDURAL_ANY_PHASE`)
- [ ] `autonomy_definitions.py`: schema + category list entry
- [ ] `autonomy_tools.py`: `t_*` function + `AUTONOMY_DISPATCH` entry
- [ ] `lineage.py`: metadata entry with non-None `spec_command`
- [ ] `transport.py`: `_MockScreen.inject` branch
- [ ] `unit_test_spec_tools.py`: `Case` + `KNOWN_MACROS` entry
- [ ] Run `scripts/generate_tools_config.py`
- [ ] Run `scripts/unit_test_spec_tools.py` (with the env vars above)
- [ ] Smoke-test through `scripts/beamtimehero spec-write <tool> --justification "..."`

For a new non-SPEC tool:

- [ ] `definitions.py`: schema (no `justification`)
- [ ] `executor.py`: `elif` branch with input validation + path confinement
- [ ] `lineage.py`: metadata entry with `spec_command: None`, `source: "filesystem"` (or other non-spec source)
- [ ] `config.py`: new directory constant if needed
- [ ] Run `scripts/generate_tools_config.py`
- [ ] Inline smoke test via `execute_tool(...)` and through `scripts/beamtimehero tool <name>`

For a new DB tool:

- [ ] `autonomy_definitions.py` or `definitions.py`: schema (no `justification` unless the tool genuinely needs one)
- [ ] `autonomy_tools.py` or `executor.py`: implementation
- [ ] `lineage.py`: metadata entry with `spec_command: None`, `source: "autonomy_db"`
- [ ] Run `scripts/generate_tools_config.py`
- [ ] Smoke-test through `scripts/beamtimehero db <name>`
