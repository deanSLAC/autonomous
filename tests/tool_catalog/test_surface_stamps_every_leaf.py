"""Every leaf under an agent branch carries `_agent_role`.

The motor allow-list used to be enforced in the CLI's leaf runner, which
read `args._agent_role` and skipped the check when it was absent. The
stamp was applied afterwards by walking `subs.choices` for four tree
names — `tool`, `db`, `spec-read`, `spec-write` — so leaves on
`spec-file`, `s3df`, `slack`, `xrs` and `exafs` carried no role and were
not checked. None of those five trees has a motor argument today, so
nothing was exploitable; what was wrong is that the property "a leaf an
agent can reach is a leaf the guard sees" held by coincidence.

`build_catalog_subtrees(agent_role=...)` stamps at leaf creation, and the
guard now lives in the surface's executor rather than in the leaf runner,
so the coincidence is not load-bearing any more. This test pins the
stamp, and records the four-of-nine gap it replaced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.agent_roles import SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import (  # noqa: E402
    Catalogue,
    build_surface,
    snapshot_parser,
)

ROLES = sorted(SURFACES)

OLD_STAMPED_TREES = frozenset({"tool", "db", "spec-read", "spec-write"})


@pytest.fixture(scope="module")
def catalogue():
    import beamline_tools.tool_catalog.tools  # noqa: F401 — registers CAT-8

    return Catalogue.default()


def _branch(catalogue, role: str) -> dict:
    parser = argparse.ArgumentParser(prog="beamtimehero")
    subs = parser.add_subparsers(dest="tree", metavar="<tree>")
    build_surface(SURFACES[role], catalogue).attach(subs)
    return snapshot_parser(parser)["children"][role]


def _leaves(node: dict, prefix: tuple[str, ...] = ()):
    """Yield `(path, defaults)` for every node that dispatches a tool."""
    if node["defaults"].get("_tool_name"):
        yield prefix, node["defaults"]
    for name, child in node["children"].items():
        yield from _leaves(child, prefix + (name,))


@pytest.mark.parametrize("role", ROLES)
def test_every_leaf_carries_the_agent_role(catalogue, role):
    leaves = list(_leaves(_branch(catalogue, role)))
    assert leaves, f"{role} branch has no tool leaves"
    unstamped = [
        "/".join(path) for path, defaults in leaves
        if defaults.get("_agent_role") != role
    ]
    assert not unstamped, (
        f"{len(unstamped)} leaves under {role} carry no _agent_role: "
        f"{sorted(unstamped)[:8]}"
    )


@pytest.mark.parametrize("role", ROLES)
def test_the_stamp_now_reaches_the_other_five_trees(catalogue, role):
    """Records the gap this closed: leaves exist on trees the old walk
    never visited, and they are stamped now."""
    reached = {
        path[0] for path, _ in _leaves(_branch(catalogue, role))
    } - OLD_STAMPED_TREES
    assert reached, "expected leaves on trees outside the four the old walk visited"
