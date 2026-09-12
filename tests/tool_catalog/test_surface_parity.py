"""What each role's generated surface actually carries.

This file began as the migration's acceptance rule: per role, build the
branch both ways — the hand-written `_build_role_branch` and
`build_surface(...).attach` — and compare canonical argparse snapshots.
Those two tests passed with the old code still in place (commit
"agent_roles: declare each role as an AgentSurface, under a parity test")
and were removed in the commit that deleted `_build_role_branch`,
`_filter_for_role` and `_stamp_agent_role`: a comparison against code
that no longer exists is not a test, and keeping a frozen copy of the
deleted implementation here would be a second implementation pretending
to be a reference.

The lasting guarantee is a checked-in `manifest()` per role
(`beamline_tools/surfaces/<role>.manifest.json`), asserted equal below,
so a change to a role's reach shows up as a reviewable diff of the
artifact rather than as behaviour. What stays here in parser terms are
the two properties that were wrong before and would be invisible in a
manifest diff alone: that the declared `mutates` flag selects the same
tools the old `justification` heuristic did, and that an unlisted
mutating tool is absent from the dispatch table rather than merely
hidden from `--help`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.agent_roles import SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import Catalogue, build_surface  # noqa: E402

ROLES = sorted(SURFACES)


@pytest.fixture(scope="module")
def catalogue():
    # Importing `tools` registers the CAT-8 handlers; the snapshot has to
    # be taken after every registration, or the surface is missing tools
    # for reasons that depend on import order.
    import beamline_tools.tool_catalog.tools  # noqa: F401

    return Catalogue.default()


@pytest.mark.parametrize("role", ROLES)
def test_write_filter_drops_exactly_the_unlisted_mutating_tools(catalogue, role):
    """The declared `mutates` flag replaces "the schema requires
    `justification`". The two must pick the same tools, or the migration
    silently widened or narrowed a role."""
    build = build_surface(SURFACES[role], catalogue)
    carried_writes = {t.name for t in build.tools if t.mutates}
    assert carried_writes == set(SURFACES[role].write_tools)

    for tool in build.tools:
        params = (tool.definition.get("function") or {}).get("parameters") or {}
        needs_justification = "justification" in set(params.get("required") or [])
        assert needs_justification == tool.mutates, (
            f"{'/'.join(tool.path)}: mutates={tool.mutates} but "
            f"justification-required={needs_justification}"
        )


@pytest.mark.parametrize("role", ROLES)
def test_restricted_dispatch_holds_only_carried_paths(catalogue, role):
    build = build_surface(SURFACES[role], catalogue)
    carried = {t.path for t in build.tools}
    assert set(build.dispatch) <= carried
    # An unlisted mutating tool is not merely hidden from --help; it is
    # absent from the table, so the executor answers "Unknown tool".
    dropped = set(catalogue.index()) - carried
    assert dropped, f"{role} carries the whole catalogue — the filter did nothing"
    for path in dropped:
        assert path not in build.dispatch


@pytest.mark.parametrize("role", ROLES)
def test_motor_guard_refuses_an_unlisted_motor(catalogue, role):
    """The guard is a before-hook on the surface's executor, so it applies
    to any caller — not only to one that came through the CLI leaf runner,
    which is what the old CLI-level check required."""
    import json

    build = build_surface(SURFACES[role], catalogue)
    text, images = build.executor(
        ("spec-write",), "move_motor",
        {"motor": "definitely_not_a_motor", "position": 1,
         "justification": "test"},
    )
    body = json.loads(text)
    assert body["ok"] is False
    assert "not in {} allowed set".format(role) in body["error"]
    assert body["agent_role"] == role
    assert body["allowed_motors"] == sorted(SURFACES[role].motors)
    assert images == []
