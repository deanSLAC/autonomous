"""The merged lineage is complete, and `mutates` says what it claims.

Three properties, each of which was broken or unstated before:

1. **Every CAT-8 tool has a lineage entry.** `get_holder_time_budget` had
   an arg model, a definition and a handler but no lineage row, so
   `categorize()` fell through to `("tool",)` and the tool sat on the
   wrong tree — reachable only by an agent granted the whole `tool`
   branch, and invisible to the `db` branch every role already carries.
   A count comparison would not have caught it (24 models, 23 entries
   looks like a rounding error); naming the missing key does.

2. **`mutates` agrees with the schema.** `mutates` is now declared
   rather than inferred from "does the schema require `justification`",
   and the two must not disagree: the schema is what the agent sees and
   `mutates` is what the write filter and the action log act on. This is
   the test that keeps the seeding honest after the inference is gone.

3. **The four db uploads are audited writes.** They were the concrete
   bug behind the change. They require `justification`, they write to
   the autonomy DB, and the old "`justification` in `required`" rule
   classified them as harmless because `source == "autonomy_db"` is
   checked first in `categorize()` — so each role's write set held 42
   names while only 38 of them were filtered on.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from beamline_tools.tool_catalog.arg_models import ARG_MODELS  # noqa: E402
from beamline_tools.tool_catalog.definitions import (  # noqa: E402
    AUTONOMY_TOOL_DEFINITIONS,
)
from beamline_tools.tool_catalog.lineage import TOOL_LINEAGE  # noqa: E402

# The autonomy tools that require a justification and are written to the
# action log, despite living on `db` rather than `spec-write`.
AUDITED_DB_TOOLS = frozenset({
    "record_alignment_flux",
    "record_completed_scan",
    "upload_sample_alignment_results",
    "upload_sample_survey_results",
})


def _requires_justification(tool_def: dict) -> bool:
    params = (tool_def.get("function") or {}).get("parameters") or {}
    return "justification" in set(params.get("required") or [])


def test_every_arg_model_has_a_lineage_entry():
    missing = sorted(name for name in ARG_MODELS if name not in TOOL_LINEAGE)
    assert not missing, (
        f"no lineage entry for {missing} — categorize() falls through to "
        "('tool',) without one, putting the tool on a branch no role's "
        "`db` grant reaches"
    )


def test_every_autonomy_definition_has_a_lineage_entry():
    missing = sorted(
        d["function"]["name"]
        for d in AUTONOMY_TOOL_DEFINITIONS
        if d["function"]["name"] not in TOOL_LINEAGE
    )
    assert not missing, f"no lineage entry for {missing}"


def test_mutates_matches_the_schema():
    """`mutates` and "requires justification" must never disagree."""
    disagree = []
    for tool_def in AUTONOMY_TOOL_DEFINITIONS:
        name = tool_def["function"]["name"]
        declared = TOOL_LINEAGE[name].get("mutates")
        assert isinstance(declared, bool), f"{name}: mutates must be a bool"
        if declared != _requires_justification(tool_def):
            disagree.append(
                f"{name}: mutates={declared} but "
                f"justification-required={_requires_justification(tool_def)}"
            )
    assert not disagree, "\n".join(disagree)


def test_the_four_audited_db_tools_mutate():
    for name in sorted(AUDITED_DB_TOOLS):
        assert TOOL_LINEAGE[name]["mutates"] is True, (
            f"{name} requires a justification and writes to the autonomy DB; "
            "mutates=False would let every role call it unlisted"
        )


def test_no_other_autonomy_tool_mutates():
    """The write set is exactly those four — a fifth is a policy change."""
    mutating = {
        d["function"]["name"]
        for d in AUTONOMY_TOOL_DEFINITIONS
        if TOOL_LINEAGE[d["function"]["name"]]["mutates"]
    }
    assert mutating == set(AUDITED_DB_TOOLS)


def test_registration_reaches_categorize_without_a_patch():
    """register_lineage updates upstream's dict in place, so the three
    `categorize.TOOL_LINEAGE = ...` monkey-patches are now no-ops."""
    import beamtimehero_cli.tool_catalog.categorize as categorize_mod

    assert TOOL_LINEAGE is categorize_mod.TOOL_LINEAGE
