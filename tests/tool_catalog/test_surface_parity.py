"""The generated agent branch equals the hand-built one, role by role.

This is the acceptance rule for the migration, and it is a precondition
for deleting anything: `_filter_for_role`, `_stamp_agent_role`,
`_build_role_branch` and the motor loop in `scripts/beamtimehero` stay
until this file is green, so "the generated surface is the same surface"
is a measured claim rather than a reading of the code.

Phase A (this file, for now) compares argparse trees: every command,
every flag, every `type`/`choices`/`default`/`nargs`/`help`, and the
`_tool_name`/`_tool_category` dispatch defaults, at every depth. Once the
old code is gone there is nothing to compare against, so step 3a.5 flips
this to equality against a checked-in `manifest()`.

One difference is expected and is the fix rather than a regression: the
old `_stamp_agent_role` walked `subs.choices` for four tree names only
(`tool`, `db`, `spec-read`, `spec-write`), so leaves on `spec-file`,
`s3df`, `slack`, `xrs` and `exafs` carried no `_agent_role` and were
never motor-checked. `build_catalog_subtrees(agent_role=...)` stamps at
leaf creation. So `_agent_role` is stripped for the comparison here and
asserted separately in `test_surface_stamps_every_leaf.py`.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.agent_roles import AGENT_ROLES, SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import (  # noqa: E402
    Catalogue,
    build_surface,
    snapshot_parser,
    strip_keys,
)

ROLES = sorted(SURFACES)


def _load_cli_script():
    """Import `scripts/beamtimehero` as a module.

    It is an executable script with no `.py` suffix, so it cannot be
    imported by name. Its module body is import-safe — the entry point is
    behind `if __name__ == "__main__"` — and the simulation bootstrap it
    runs only touches gitignored fixture directories.
    """
    path = REPO_ROOT / "scripts" / "beamtimehero"
    loader = SourceFileLoader("autonomy_cli_script", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli_script()


@pytest.fixture(scope="module")
def catalogue():
    # Importing `tools` registers the CAT-8 handlers; the snapshot has to
    # be taken after every registration, or the surface is missing tools
    # for reasons that depend on import order.
    import beamline_tools.tool_catalog.tools  # noqa: F401

    return Catalogue.default()


def _root() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    parser = argparse.ArgumentParser(prog="beamtimehero")
    return parser, parser.add_subparsers(dest="tree", metavar="<tree>")


def _old_branch(cli, role: str) -> dict:
    parser, subs = _root()
    cli._build_role_branch(subs, role, AGENT_ROLES[role])
    return snapshot_parser(parser)["children"][role]


def _new_branch(cli, catalogue, role: str) -> dict:
    parser, subs = _root()
    build = build_surface(SURFACES[role], catalogue)
    branch_subs = build.attach(subs)
    # `steering` is autonomy's own subtree and is not part of the
    # catalogue, so the surface does not generate it. It is hung off the
    # subparsers `attach` returns, which is why `attach` returns them.
    cli._build_steering_subtree(branch_subs)
    return snapshot_parser(parser)["children"][role]


@pytest.mark.parametrize("role", ROLES)
def test_generated_branch_matches_hand_built_branch(cli, catalogue, role):
    old = strip_keys(_old_branch(cli, role), ("_agent_role",))
    new = strip_keys(_new_branch(cli, catalogue, role), ("_agent_role",))
    assert new == old


@pytest.mark.parametrize("role", ROLES)
def test_generated_branch_carries_the_same_leaves(cli, catalogue, role):
    """The same assertion at a granularity that names what differs.

    The tree comparison above fails as one opaque dict inequality; this
    one fails as a set difference of `tree/leaf` paths, which is the
    first thing anybody debugging a write-filter change wants to see.
    """
    def leaves(node: dict) -> set[str]:
        out = set()
        for tree_name, tree in node["children"].items():
            for leaf_name, leaf in tree["children"].items():
                if leaf["defaults"].get("_tool_name"):
                    out.add(f"{tree_name}/{leaf_name}")
                out |= {
                    f"{tree_name}/{leaf_name}/{sub}"
                    for sub in leaf["children"]
                }
        return out

    assert leaves(_new_branch(cli, catalogue, role)) == leaves(_old_branch(cli, role))


@pytest.mark.parametrize("role", ROLES)
def test_write_filter_drops_exactly_the_unlisted_mutating_tools(catalogue, role):
    """The declared `mutates` flag replaces "the schema requires
    `justification`". The two must pick the same tools, or the migration
    silently widened or narrowed a role."""
    build = build_surface(SURFACES[role], catalogue)
    allowed = SURFACES[role].write_tools
    carried_writes = {t.name for t in build.tools if t.mutates}
    assert carried_writes == set(allowed)

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
    dropped = (set(catalogue.index()) - carried)
    assert dropped, f"{role} carries the whole catalogue — the filter did nothing"
    for path in dropped:
        assert path not in build.dispatch
