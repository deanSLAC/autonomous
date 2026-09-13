#!/usr/bin/env python3
"""Verify ../beamtimehero_cli sits on the commit this repo is pinned to.

The toolbelt is an editable install, so `import beamtimehero_cli` resolves
into a sibling git checkout's working tree. Whatever is checked out there is
what autonomy runs: a pull in that repo changes this one's behaviour with no
diff on this side, nothing reinstalls, and nothing notices.

chemcat pins the same dependency at the point where its sibling checkout is
*created* — the CI clone and the Docker build context, with a
`BEAMTIMEHERO_CLI_REF` repo variable as the override. Autonomy has no such
point; the checkout is made by hand on the dev box and on the beamline
machine. So the pin is recorded in `beamtimehero_cli.pin` and verified here,
at start-up, under the same override variable.

Verification, never checkout: this does not move the sibling repo. It may
hold work in progress and standing on that is worse than the drift.

Stdlib only, and the checkout is located with `find_spec` rather than by
importing the package. `beamtimehero_cli.config` reads BEAMTIMEHERO_DATA_DIR
at import time, so importing it here — ahead of `deployment_paths` — would
put this repo's writable state, the action log and the SPEC safety switch
among it, inside the toolbelt's checkout. See deployment_paths.py for the
day that happened.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = REPO_ROOT / "beamtimehero_cli.pin"
OVERRIDE_ENV = "BEAMTIMEHERO_CLI_REF"

#: Checkout is on the pinned commit.
OK = "ok"
#: $BEAMTIMEHERO_CLI_REF was set and the checkout matches it.
OVERRIDE = "override"
#: Checkout is on some other commit than the one asked for.
MISMATCH = "mismatch"
#: beamtimehero_cli.pin is missing, empty, or all comment.
NO_PIN = "no-pin"
#: No git checkout to interrogate — a wheel install, or git unavailable.
UNVERIFIABLE = "unverifiable"

_PASSING = (OK, OVERRIDE)


@dataclass(frozen=True)
class PinStatus:
    state: str
    message: str

    @property
    def ok(self) -> bool:
        return self.state in _PASSING


def _git(root: Path, *args: str) -> str | None:
    """`git -C root *args`, or None if git is absent or the command fails."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def read_pin() -> str | None:
    """First non-comment, non-blank token in the pin file."""
    try:
        text = PIN_FILE.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            return token
    return None


def checkout_root() -> Path | None:
    """The git work tree backing the installed `beamtimehero_cli`, if any.

    `find_spec` on a top-level name locates the package without executing
    it, which is the point — see the module docstring.
    """
    try:
        spec = importlib.util.find_spec("beamtimehero_cli")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    top = _git(Path(spec.origin).resolve().parent, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def check(env: "os._Environ[str] | dict[str, str] | None" = None) -> PinStatus:
    env = os.environ if env is None else env

    wanted = (env.get(OVERRIDE_ENV) or "").strip()
    overridden = bool(wanted)
    source = f"${OVERRIDE_ENV}"
    if not overridden:
        wanted = read_pin() or ""
        source = PIN_FILE.name
        if not wanted:
            return PinStatus(
                NO_PIN,
                f"{PIN_FILE} names no commit. Restore it, or set "
                f"{OVERRIDE_ENV} to the ref you mean.",
            )

    root = checkout_root()
    if root is None:
        return PinStatus(
            UNVERIFIABLE,
            "beamtimehero_cli is not importable from a git checkout, so the "
            f"pin cannot be verified. requirements.txt installs it with -e, "
            f"which keeps it one: pip install -e ../beamtimehero_cli. To "
            f"launch anyway, set {OVERRIDE_ENV}=HEAD.",
        )

    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return PinStatus(UNVERIFIABLE, f"cannot read HEAD of {root}.")

    target = _git(root, "rev-parse", "--verify", f"{wanted}^{{commit}}")
    if target is None:
        return PinStatus(
            MISMATCH,
            f"{source} names {wanted!r}, which {root} does not know.\n"
            f"  fetch it:  git -C {root} fetch origin",
        )

    if target != head:
        return PinStatus(
            MISMATCH,
            f"{root}\n"
            f"  is at    {head}\n"
            f"  {source} wants {target}\n"
            f"  move the checkout:  git -C {root} checkout {target}\n"
            f"  or advance the pin: edit {PIN_FILE.name}, run the suite, "
            f"and bump chemcat's {OVERRIDE_ENV} to match\n"
            f"  or ignore it once:  {OVERRIDE_ENV}=HEAD ./scripts/start.sh",
        )

    note = ""
    if _git(root, "status", "--porcelain"):
        note = (
            f"\n  note: {root} has uncommitted changes, so the running code "
            f"is not exactly {head[:12]}"
        )
    if overridden:
        return PinStatus(
            OVERRIDE,
            f"{source}={wanted} — running {head[:12]}, pin not enforced.{note}",
        )
    return PinStatus(OK, f"beamtimehero_cli at {head[:12]}, as pinned.{note}")


def main() -> int:
    status = check()
    if not status.ok:
        print(f"[cli-pin] {status.message}", file=sys.stderr)
        return 1
    print(f"[cli-pin] {status.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
