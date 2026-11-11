#!/usr/bin/env python3
"""Drop pure action-pin bumps from the v1 gate's changed paths.

``update-v1-tag.yml`` holds ``v1`` for a person whenever the range touches the
gnome-e2e composite action, because ``e2e.yml`` cannot boot that lane. Most of
those changes are Renovate swapping one pinned commit SHA for another in a
``uses:`` line (projectbluefin/actions digest bumps), and each one froze ``v1``
until someone forced it (#1127, #1140). This filter is the gate's version of
the hive's pin-only rule: a file under ``PIN_ONLY_PREFIXES`` whose whole diff
in the range is such swaps is left out of the plan. Anything else in the file,
or a ref that is not a full commit SHA on both sides, keeps it in (fail-closed).

Usage:
    python3 scripts/v1_gate_pins.py PREVIOUS SHA < changed.txt > kept.txt

Reads changed paths on stdin and prints the ones the plan still needs. Each
dropped path is reported on stderr.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Paths where a pure pin bump needs no VM. Only the composite action: its
# changes are the ones that hold v1; e2e.yml pin bumps still boot as before.
PIN_ONLY_PREFIXES = (".github/actions/gnome-e2e/",)

# One `uses: owner/repo[/path]@<40-hex sha>` line, with an optional comment.
_USES = re.compile(
    r"^\s*(?:-\s+)?uses:\s*(?P<action>[\w.-]+/[\w./-]+)@(?P<ref>[0-9a-f]{40})\s*(?:#.*)?$"
)


def is_pin_bump(diff: str) -> bool:
    """True when a ``git diff -U0`` of one file only swaps pinned action SHAs.

    Every removed line must pair, in order, with an added line naming the same
    action at a different full SHA. Comments after the pin may change.
    """
    removed: list[re.Match[str]] = []
    added: list[re.Match[str]] = []
    for line in diff.splitlines():
        if line.startswith(("---", "+++")):
            continue
        if line.startswith(("-", "+")):
            match = _USES.match(line[1:])
            if match is None:
                return False
            (removed if line[0] == "-" else added).append(match)
    if not removed or len(removed) != len(added):
        return False
    return all(
        old["action"] == new["action"] and old["ref"] != new["ref"]
        for old, new in zip(removed, added)
    )


def file_diff(previous: str, sha: str, path: str) -> str:
    """Return the zero-context diff of one path between two commits."""
    return subprocess.run(
        ["git", "diff", "-U0", "--no-color", previous, sha, "--", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    previous, sha = argv[1], argv[2]
    for raw in sys.stdin.read().splitlines():
        path = raw.strip()
        if not path:
            continue
        if path.startswith(PIN_ONLY_PREFIXES) and is_pin_bump(
            file_diff(previous, sha, path)
        ):
            print(f"pin bump only, no VM needed: {path}", file=sys.stderr)
            continue
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
