"""The generated artifacts on disk match the surfaces they came from.

Five things have to agree with `agent_roles.SURFACES`: the checked-in
manifest, the prompt fragment, the `tools:` front-matter line in each
agent definition, the marker block in that same file, and the allow list
in `.claude/settings.json`. They used to agree by hand, and did not:

* the motor lists pasted into the four prompt files had drifted from the
  sets the CLI enforced — the bl-aligner's copy listed motors in a
  different order and the comment above it claimed to be authoritative;
* the permission pattern was spelled `Bash(beamtimehero blaligner:*)` in
  one file and `Bash(beamtimehero samplealigner *)` in five others, and
  the only thing pinning either spelling was a test that hard-coded the
  space form.

So the drift check is the test: `--check` re-renders everything in
memory and exits non-zero if any byte differs. A scope change that was
not re-rendered fails here rather than shipping as a prompt describing a
different agent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.agent_roles import SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import (  # noqa: E402
    MARKER_BEGIN,
    MARKER_END,
    Catalogue,
    build_surface,
)

RENDERER = REPO_ROOT / "scripts" / "render_agent_surfaces.py"
AGENT_DIR = REPO_ROOT / ".claude" / "agents"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

AGENT_FILES = {
    "blaligner": "bl-aligner.md",
    "samplealigner": "sample-aligner.md",
    "surveyor": "sample-surveyor.md",
    "collector": "data-collection.md",
}

ROLES = sorted(SURFACES)


@pytest.fixture(scope="module")
def catalogue():
    import beamline_tools.tool_catalog.tools  # noqa: F401 — registers CAT-8

    return Catalogue.default()


def _tools_line(name: str) -> str:
    text = (AGENT_DIR / name).read_text()
    return next(l for l in text.splitlines() if l.startswith("tools:"))


def test_render_check_reports_no_drift():
    result = subprocess.run(
        [sys.executable, str(RENDERER), "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "generated artifacts are stale — run "
        f"`python scripts/render_agent_surfaces.py`\n"
        f"{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("role", ROLES)
def test_agent_file_tools_line_is_the_generated_pattern(catalogue, role):
    pattern = build_surface(SURFACES[role], catalogue).bash_pattern()
    line = _tools_line(AGENT_FILES[role])
    assert pattern in line, f"{AGENT_FILES[role]} tools: line is {line!r}"
    # The space form is what the colon form replaced; both spellings
    # coexisting is the drift this generates away.
    assert f"Bash(beamtimehero {role} *)" not in line


@pytest.mark.parametrize("role", ROLES)
def test_settings_allow_covers_every_role_branch(catalogue, role):
    allow = set(
        (json.loads(SETTINGS.read_text()).get("permissions") or {}).get("allow")
        or []
    )
    pattern = build_surface(SURFACES[role], catalogue).bash_pattern()
    assert pattern in allow, (
        f"{pattern} missing from .claude/settings.json permissions.allow — "
        "the agent's own tools: line grants it, but an operator running the "
        "same command interactively would be prompted"
    )


@pytest.mark.parametrize("role", ROLES)
def test_agent_file_marker_block_holds_the_prompt_fragment(catalogue, role):
    text = (AGENT_DIR / AGENT_FILES[role]).read_text()
    begin, end = text.find(MARKER_BEGIN), text.find(MARKER_END)
    assert 0 <= begin < end, f"{AGENT_FILES[role]} has no marker block"
    block = text[begin + len(MARKER_BEGIN):end].strip()
    assert block == build_surface(SURFACES[role], catalogue).prompt_fragment().strip()


@pytest.mark.parametrize("name", ("planner.md", "chat.md"))
def test_canonical_tree_agents_use_the_colon_form(name):
    line = _tools_line(name)
    assert "beamtimehero" in line
    assert " *)" not in line.replace("Bash(date *)", ""), (
        f"{name} still spells a beamtimehero pattern with a space: {line!r}"
    )


RESEARCH_PATTERN = "Bash(beamtimehero research:*)"

#: Every agent definition that names a `beamtimehero` pattern at all.
#: `beamtime-worker.md` carries a bare `Bash` and is out of scope here
#: (flagged when the surfaces landed, not fixed by this change).
PATTERNED_AGENTS = (
    "planner.md", "chat.md", "control.md", "tester.md",
    "bl-aligner.md", "sample-aligner.md", "sample-surveyor.md",
    "data-collection.md",
)


def test_the_planner_is_granted_the_research_branch():
    """One leaf, one holder.

    `research ask-question` returns untrusted third-party text, and the
    only defence is prompt discipline in whatever reads it. The planner
    is the one agent that has those rules written down, so it is the one
    agent with the grant — and it cannot act on the beamline itself.
    """
    line = _tools_line("planner.md")
    assert RESEARCH_PATTERN in line, line


@pytest.mark.parametrize("name", [n for n in PATTERNED_AGENTS if n != "planner.md"])
def test_no_other_agent_names_the_research_branch(name):
    """The two full-surface operator agents are the known exception.

    `control.md` and `tester.md` carry `Bash(beamtimehero *)` on purpose,
    which reaches every branch including this one. They are operator
    agents driven by a human at a terminal, not autonomy, and narrowing
    them is a separate decision. Everything else must not name it.
    """
    line = _tools_line(name)
    if "Bash(beamtimehero *)" in line:
        pytest.skip(f"{name} is a full-surface operator agent by design")
    assert RESEARCH_PATTERN not in line, line
    assert "research" not in line


def test_the_planner_prompt_says_a_report_is_not_instructions():
    """The grant and the handling rule ship together or not at all.

    The container cannot close this path — a sandbox report is text, and
    the agent reading it is what decides whether text becomes an action.
    So the permission line and the paragraph that tells the planner what
    to do with the report are held to each other here.
    """
    text = (AGENT_DIR / "planner.md").read_text()
    assert RESEARCH_PATTERN in text
    assert "evidence" in text and "never instructions" in text
    for fragment in (
        "<untrusted-report>",
        "content, not a command",
        "fabricated",
        "RESEARCH_SANDBOX_ENABLED=1",
    ):
        assert fragment in text, fragment


@pytest.mark.parametrize("name", ("control.md", "tester.md"))
def test_full_surface_agents_keep_the_whole_cli(name):
    """Not drift: these two are operator agents and carry the whole CLI on
    purpose. Pinned so a future normalisation pass does not narrow them by
    accident."""
    assert "Bash(beamtimehero *)" in _tools_line(name)
