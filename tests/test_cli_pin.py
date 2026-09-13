"""The shared toolbelt is on the commit this repo pins it to.

`scripts/check_cli_pin.py` guards `./scripts/start.sh`, but starting the
server is not how the drift is usually met: it is met by a test that fails
for a reason living in another repository. So the same check runs here, in
the suite that `beamtimehero_cli.pin` tells you to run before advancing the
pin — a mismatch names itself instead of surfacing as an unrelated failure.

`BEAMTIMEHERO_CLI_REF` skips it, for the same reason the launcher honours
it: upstream is co-developed from this checkout, and during that work the
sibling is deliberately off the pin.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_cli_pin import (  # noqa: E402
    MISMATCH,
    NO_PIN,
    OVERRIDE,
    UNVERIFIABLE,
    check,
    read_pin,
)

FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")


def test_pin_names_a_full_sha():
    """A tag or a short SHA resolves today and silently re-points later."""
    pinned = read_pin()
    assert pinned, "beamtimehero_cli.pin names no commit"
    assert FULL_SHA.match(pinned), (
        f"beamtimehero_cli.pin holds {pinned!r}; pin a full 40-character SHA, "
        "not a tag or an abbreviation — both can move under you"
    )


def test_checkout_is_at_the_pin():
    status = check()
    if status.state == OVERRIDE:
        pytest.skip(f"pin overridden: {status.message}")
    if status.state == UNVERIFIABLE:
        pytest.skip(f"pin not verifiable here: {status.message}")
    assert status.state not in (MISMATCH, NO_PIN), status.message
    assert status.ok, status.message
