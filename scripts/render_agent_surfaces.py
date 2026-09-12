#!/usr/bin/env python3
"""Generate every artifact that has to agree with an agent's surface.

One declaration — `beamline_tools.agent_roles.SURFACES` — and five files
per role derived from it:

    beamline_tools/surfaces/<role>.manifest.json   the resolved surface
    beamline_tools/surfaces/<role>.prompt.md       the prompt fragment
    .claude/agents/<file>.md    `tools:` front-matter + the marker block
    .claude/settings.json       checked, not written (see --check output)

Before this existed, each of those was written by hand and had to agree
with the others by hand. They did not. The motor lists pasted into the
four prompt files had drifted from the sets the CLI actually enforced;
the shell permission line was spelled `Bash(beamtimehero blaligner:*)`
in one file and `Bash(beamtimehero samplealigner *)` in five others,
with no rule about which; and one test hard-coded the space form, so the
spelling was pinned by a test rather than chosen.

Usage:

    python scripts/render_agent_surfaces.py            # write
    python scripts/render_agent_surfaces.py --check    # exit 1 on drift

`--check` writes nothing and prints a unified diff of every file that
would change. It is what `tests/tool_catalog/test_agent_files_generated.py`
runs, so a change to a role's scope that was not re-rendered fails the
suite instead of going out as a prompt that describes a different agent.

The marker block must already exist in an agent file:

    <!-- surface:begin -->
    ...generated...
    <!-- surface:end -->

This script rewrites what is between the markers and refuses to guess
where they belong. The one-time insertion was a reviewed edit that
deleted the hand-pasted motor lists they replaced; a renderer that
re-inserted a missing block would put it back in the wrong place, or
twice, and nobody would notice until an agent read it.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Deployment paths (data dir, safety switches) before any other repo import.
import deployment_paths  # noqa: E402,F401

# Rendering must never touch a real beamline: the catalogue import reaches
# transport config, and this script is run from a laptop and from CI.
os.environ.setdefault("SPEC_MOCK", "1")

from beamline_tools.agent_roles import SURFACES  # noqa: E402
from beamtimehero_cli.agent_surface import (  # noqa: E402
    MARKER_BEGIN,
    MARKER_END,
    Catalogue,
    build_surface,
)

SURFACE_DIR = ROOT / "beamline_tools" / "surfaces"
AGENT_DIR = ROOT / ".claude" / "agents"
SETTINGS = ROOT / ".claude" / "settings.json"

#: role -> the agent definition whose prompt and permission it governs.
#: Not derivable: the CLI branch is `surveyor` and the agent is
#: `sample-surveyor`, `collector` is `data-collection`.
AGENT_FILES: dict[str, str] = {
    "blaligner": "bl-aligner.md",
    "samplealigner": "sample-aligner.md",
    "surveyor": "sample-surveyor.md",
    "collector": "data-collection.md",
}

#: Agent files that reach canonical trees rather than a role branch. Their
#: `tools:` lines are normalised to the colon form, nothing else.
NORMALISE_ONLY: tuple[str, ...] = ("planner.md", "chat.md")

#: Left alone on purpose. `control.md` and `tester.md` carry
#: `Bash(beamtimehero *)` because they are full-surface operator agents,
#: which is a deliberate exception rather than drift.
FULL_SURFACE: tuple[str, ...] = ("control.md", "tester.md")


class DriftError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# The `tools:` front-matter line
# ---------------------------------------------------------------------------

def _normalise_bash_entry(entry: str) -> str:
    """`Bash(beamtimehero db *)` -> `Bash(beamtimehero db:*)`.

    Only `beamtimehero` patterns: the colon is claude-code's own
    delimiter and `.claude/settings.json` already spells the CLI's
    patterns that way, but `Bash(date *)` is not ours to restyle.
    """
    entry = entry.strip()
    if not (entry.startswith("Bash(beamtimehero ") and entry.endswith("*)")):
        return entry
    inner = entry[len("Bash("):-1]           # e.g. "beamtimehero db *"
    if inner.endswith(" *"):
        inner = inner[:-2] + ":*"
    return f"Bash({inner})"


def _rewrite_tools_line(line: str, role: str | None, pattern: str | None) -> str:
    """Rewrite one `tools:` front-matter line.

    Every `beamtimehero` pattern is normalised to the colon form. If a
    `role` is given, the entry naming that role's branch is replaced with
    the generated `pattern` outright, so the permission cannot disagree
    with the surface it is supposed to grant.
    """
    prefix, _, value = line.partition(":")
    out: list[str] = []
    replaced = False
    for entry in value.split(","):
        entry = _normalise_bash_entry(entry)
        if role is not None and entry.startswith(f"Bash(beamtimehero {role}"):
            entry = pattern
            replaced = True
        out.append(entry)
    if role is not None and not replaced:
        raise DriftError(
            f"no `Bash(beamtimehero {role} ...)` entry on the tools: line — "
            f"add one (it should read {pattern}) so the agent can reach its "
            "branch at all"
        )
    return f"{prefix}: " + ", ".join(out)


# ---------------------------------------------------------------------------
# The marker block
# ---------------------------------------------------------------------------

def _replace_marker_block(text: str, body: str, where: Path) -> str:
    begin = text.find(MARKER_BEGIN)
    end = text.find(MARKER_END)
    if begin < 0 or end < 0:
        raise DriftError(
            f"{where.name} has no {MARKER_BEGIN} / {MARKER_END} block. Insert "
            "one where the surface description belongs; this script will not "
            "guess the position."
        )
    if end < begin:
        raise DriftError(f"{where.name}: {MARKER_END} precedes {MARKER_BEGIN}")
    head = text[:begin + len(MARKER_BEGIN)]
    tail = text[end:]
    return f"{head}\n\n{body.strip()}\n\n{tail}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _catalogue() -> Catalogue:
    # Importing `tools` registers the CAT-8 handlers into
    # tools_core.DISPATCH; Catalogue.default() snapshots that table, so the
    # import has to come first or the CAT-8 tools resolve with no handler.
    import beamline_tools.tool_catalog.tools  # noqa: F401

    return Catalogue.default()


def render() -> dict[Path, str]:
    """Every generated file, as {path: intended content}. Writes nothing."""
    catalogue = _catalogue()
    out: dict[Path, str] = {}

    for role in sorted(SURFACES):
        build = build_surface(SURFACES[role], catalogue)

        out[SURFACE_DIR / f"{role}.manifest.json"] = (
            json.dumps(build.manifest(), indent=2, sort_keys=True) + "\n"
        )
        out[SURFACE_DIR / f"{role}.prompt.md"] = build.prompt_fragment()

        path = AGENT_DIR / AGENT_FILES[role]
        text = path.read_text()
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith("tools:"):
                lines[i] = _rewrite_tools_line(
                    line.rstrip("\n"), role, build.bash_pattern(),
                ) + "\n"
                break
        else:
            raise DriftError(f"{path.name} has no tools: front-matter line")
        out[path] = _replace_marker_block(
            "".join(lines), build.prompt_fragment(), path,
        )

    for name in NORMALISE_ONLY:
        path = AGENT_DIR / name
        lines = path.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith("tools:"):
                lines[i] = _rewrite_tools_line(line.rstrip("\n"), None, None) + "\n"
                break
        else:
            raise DriftError(f"{path.name} has no tools: front-matter line")
        out[path] = "".join(lines)

    return out


def check_settings() -> list[str]:
    """Every role's pattern must be on `.claude/settings.json`'s allow list.

    Reported rather than written: the settings file is the operator's,
    and a renderer that edited it would be reaching outside the artifacts
    it owns.
    """
    allow = set(
        (json.loads(SETTINGS.read_text()).get("permissions") or {}).get("allow")
        or []
    )
    catalogue = _catalogue()
    missing = []
    for role in sorted(SURFACES):
        pattern = build_surface(SURFACES[role], catalogue).bash_pattern()
        if pattern not in allow:
            missing.append(pattern)
    return missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render_agent_surfaces",
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument(
        "--check", action="store_true",
        help="Report drift and exit non-zero; write nothing.",
    )
    args = ap.parse_args(argv)

    try:
        intended = render()
    except DriftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    stale: list[Path] = []
    for path, content in sorted(intended.items()):
        current = path.read_text() if path.exists() else ""
        if current == content:
            continue
        stale.append(path)
        if args.check:
            rel = path.relative_to(ROOT)
            sys.stdout.writelines(
                difflib.unified_diff(
                    current.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=f"a/{rel}", tofile=f"b/{rel}",
                )
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    missing = check_settings()
    for pattern in missing:
        print(
            f"{'drift' if args.check else 'warning'}: "
            f"{pattern} is not on .claude/settings.json permissions.allow",
            file=sys.stderr,
        )

    if args.check:
        if stale or missing:
            print(
                f"\n{len(stale)} file(s) stale, {len(missing)} permission(s) "
                "missing — run scripts/render_agent_surfaces.py",
                file=sys.stderr,
            )
            return 1
        print(f"{len(intended)} generated file(s) up to date.")
        return 0

    print(f"Rendered {len(intended)} file(s); {len(stale)} changed.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
