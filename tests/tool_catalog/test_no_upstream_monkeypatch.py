"""No module attribute of `beamtimehero_cli` is reassigned from here.

Autonomy used to patch two upstream module attributes at CLI startup,
and copies of one of them lived in two more places:

    beamtimehero_cli.tool_catalog.categorize.TOOL_LINEAGE = ...
    beamtimehero_cli.cli.__main__.execute_tool = ...

Both existed because the library published its catalogue as module
globals and offered no way to add to them, so the only way to be seen
was to overwrite. Both are replaced by seams that mutate the shipped
containers in place (`register_lineage`, `register_definitions`,
`register_handlers`) or take the replacement as an argument
(`dispatch(..., executor=...)`, `run_tool_leaf(args, executor=...)`,
`build_surface(..., before=, after=)`).

The patches were worth removing beyond tidiness. They were
order-dependent in a way nothing checked: a module that read
`categorize.TOOL_LINEAGE` before `scripts/beamtimehero` ran — the UI
server, a test, `generate_tools_config.py` on a different import path —
saw the unpatched dict and put every CAT-8 tool on the wrong tree. And
patching `cli.__main__.execute_tool` reached exactly one caller; anything
importing `run_tool_leaf` from `cli.api` got the unpatched default.

This test is a grep, deliberately. A behavioural test would only cover
the paths it exercises, and the failure mode here is a path nobody
thought to exercise.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SEARCH_DIRS = ("scripts", "beamline_tools", "tests", "orchestration", "ui")

# `beamtimehero_cli.a.b = ...` — assigning to an attribute of the library
# or any of its submodules.
ASSIGN_RE = re.compile(r"beamtimehero_cli(?:\.\w+)*\.\w+\s*=(?!=)")

# Importing the module that `python -m beamtimehero_cli.cli` executes.
# Consumers import from `beamtimehero_cli.cli.api` instead: importing a
# module named `__main__` by path can leave two copies of the parser
# state in one process. Matches the import statement only — prose in a
# docstring that happens to name the module is not a dependency on it.
DUNDER_MAIN_RE = re.compile(
    r"^\s*(?:from\s+beamtimehero_cli\.cli\.__main__\s+import"
    r"|import\s+beamtimehero_cli\.cli\.__main__)"
)


def _source_files():
    for directory in SEARCH_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or "venv" in path.parts:
                continue
            yield path
    # `scripts/beamtimehero` is an executable with no suffix.
    for path in sorted((REPO_ROOT / "scripts").iterdir()):
        if path.is_file() and not path.suffix:
            yield path


def _hits(pattern: re.Pattern) -> list[str]:
    out: list[str] = []
    this_file = Path(__file__).resolve()
    for path in _source_files():
        if path.resolve() == this_file:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                out.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                )
    return out


def test_no_upstream_module_attribute_is_reassigned():
    hits = _hits(ASSIGN_RE)
    assert not hits, (
        "patching a beamtimehero_cli module attribute is order-dependent "
        "and reaches only the readers that import after it; use "
        "register_lineage/register_definitions/register_handlers, or pass "
        "the executor as an argument:\n  " + "\n  ".join(hits)
    )


def test_nothing_imports_the_cli_dunder_main_module():
    hits = _hits(DUNDER_MAIN_RE)
    assert not hits, (
        "import from beamtimehero_cli.cli.api, the supported surface:\n  "
        + "\n  ".join(hits)
    )
