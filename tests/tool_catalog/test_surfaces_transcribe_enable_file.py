"""Retiring the `enabled` gate widened nothing.

`beamline_tools/tools_config.json` used to be two things at once. The
tool-tester UI reads it as a status document — `simulated`,
`working_live`, `comments`, `sample_output`, and which tools have been
exercised against real hardware — and
`tool_catalog/__init__.py:_load_enabled_set` read the same file's
`enabled` key at import and dropped anything false from
`TOOL_DEFINITIONS`.

The second job was the wrong mechanism for the question it answered. It
was process-wide: flipping one key changed what *every* agent could see,
in a file whose other fields are UI bookkeeping, with no record of which
role the exclusion was for or why. That is why re-enabling one tool
(`list_open_interventions`) needed its own plan step. Scope is now
declared per role in `agent_roles.SURFACES` and enforced by the surface
that role's branch is built from.

The file stays; only the gate is gone. This test is the check that the
one was a faithful transcription of the other — run once, at the moment
it can still be verified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.agent_roles import SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import Catalogue, build_surface  # noqa: E402

CONFIG_PATH = REPO_ROOT / "beamline_tools" / "tools_config.json"

# Entries in tools_config.json that are not catalog tools: the bundled
# reference docs and the hand-written steering lifecycle commands. Both
# are real CLI surface, neither comes from TOOL_DEFINITIONS.
NON_TOOL_PATHS = frozenset({"ref", "steering"})

ROLES = sorted(SURFACES)


@pytest.fixture(scope="module")
def catalogue():
    import beamline_tools.tool_catalog.tools  # noqa: F401 — registers CAT-8

    return Catalogue.default()


def _config_tools() -> list[dict]:
    return json.loads(CONFIG_PATH.read_text())["tools"]


def test_the_enable_file_excludes_nothing():
    """The gate's removal is a no-op because nothing was gated.

    If a tool is ever disabled here again, this fails and names it —
    which is the point: the answer is a change to the role's surface, not
    a key in a UI status file.
    """
    disabled = sorted(t["name"] for t in _config_tools() if t.get("enabled") is False)
    assert not disabled, (
        f"{disabled} are disabled in tools_config.json, which no longer gates "
        "anything. Express the exclusion in agent_roles.SURFACES instead."
    )


def test_every_configured_tool_is_in_the_catalog(catalogue):
    """Nothing appeared or vanished when the filter went away."""
    configured = {
        t["name"] for t in _config_tools()
        if t["cli_path"] not in NON_TOOL_PATHS
    }
    catalog = {tool.name for tool in catalogue.index().values()}
    assert configured == catalog, (
        f"only in tools_config: {sorted(configured - catalog)}; "
        f"only in the catalog: {sorted(catalog - configured)} — regenerate "
        "with scripts/generate_tools_config.py"
    )


@pytest.mark.parametrize("role", ROLES)
def test_role_write_set_is_carried(catalogue, role):
    """Every name a role may mutate with is actually on its branch.

    `build_surface` refuses a write tool that is not carried, so this
    cannot silently be false — but it is the property the whole scheme
    rests on, and asserting it here says so out loud rather than relying
    on a validator nobody reads.
    """
    build = build_surface(SURFACES[role], catalogue)
    carried = {tool.name for tool in build.tools}
    missing = sorted(set(SURFACES[role].write_tools) - carried)
    assert not missing, f"{role} may write with {missing} but does not carry them"


@pytest.mark.parametrize("role", ROLES)
def test_role_carries_every_read_tool_on_a_branch_it_has(catalogue, role):
    """A role's scope is its writes and its motors, not a curated read list.

    Within the branches a role declares, the only tools it does not carry
    are mutating tools it has not been granted. A read tool going missing
    from a branch the role has would mean the tree was dropped from
    `branches`, which is a scope decision that has to be deliberate.

    Scoped to the declared branches because one tree is deliberately off
    all four roles: `research`, whose single leaf returns untrusted
    third-party text and is granted to the planner alone. See the comment
    on `agent_roles._ALL_BRANCHES`.
    """
    build = build_surface(SURFACES[role], catalogue)
    carried = {tool.path for tool in build.tools}
    declared = set(SURFACES[role].branches)
    reads = {
        path for path, tool in catalogue.index().items()
        if not tool.mutates and path[0] in declared
    }
    assert reads <= carried, sorted(
        "/".join(path) for path in (reads - carried)
    )


@pytest.mark.parametrize("role", ROLES)
def test_no_role_reaches_the_research_sandbox(catalogue, role):
    """The reason `research` is its own tree, asserted rather than assumed.

    `AgentSurface` has no `exclude` field: a branch on `branches` is
    granted in full. So the only thing keeping the research sandbox off
    these four agents is that the leaf does not share a branch with
    anything they need — and the only thing keeping *that* true is this
    test. If it fails, either a role gained `"research"` or the leaf moved
    onto a shared tree; both need the prompt rules in
    `.claude/agents/planner.md` written into that agent first.
    """
    build = build_surface(SURFACES[role], catalogue)
    assert "research" not in {tool.tree[0] for tool in build.tools}
    assert "research" not in SURFACES[role].branches
    assert "research" not in build.manifest()["surface"]["branches"]
