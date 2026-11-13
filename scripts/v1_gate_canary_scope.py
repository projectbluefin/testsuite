#!/usr/bin/env python3
"""List the changed gnome-e2e action steps that the GNOME OS canary skips.

The v1 gate and the PR VM check let a passing GNOME OS canary stand in for a
hand check of the gnome-e2e composite action. The canary runs that action with
``suite: gnomeos-canary``, so a step whose ``if:`` excludes that suite (the
``scripts/assert_passed.py`` gate step, for one) never runs under it. A change
to such a step is not covered by a canary pass and must still hold for a
person.

Known limit: a suite-conditional branch inside a shell step the canary does run
(``if [[ "${GNOME_E2E_SUITE}" == ... ]]``) is not split out; the canary runs
the step, just not every branch of it.

Usage:
    python3 scripts/v1_gate_canary_scope.py BASE HEAD

Prints one line per changed step the canary skips (nothing when the canary runs
every changed step). Fails closed: if either side of the action cannot be read
or parsed, it prints a marker line so the gate holds.
"""

from __future__ import annotations

import subprocess
import sys

try:
    import yaml
except ImportError:  # fail closed: the gate holds with the reason printed
    yaml = None

ACTION = ".github/actions/gnome-e2e/action.yml"
CANARY_SUITE = "gnomeos-canary"


def canary_skips(step: dict) -> bool:
    """True when the step's ``if:`` keeps it from running for the canary suite."""
    cond = str(step.get("if", "")).replace('"', "'")
    if not cond:
        return False
    if f"inputs.suite != '{CANARY_SUITE}'" in cond:
        return True
    # A condition that names only other suites (`inputs.suite == 'extensions'`).
    return "inputs.suite ==" in cond and f"'{CANARY_SUITE}'" not in cond


def _steps(text: str | None) -> dict[str, dict]:
    if text is None:
        return {}
    doc = yaml.safe_load(text) or {}
    steps = (doc.get("runs") or {}).get("steps") or []
    keyed: dict[str, dict] = {}
    for index, step in enumerate(steps):
        key = step.get("id") or step.get("name") or f"step {index + 1}"
        keyed[str(key)] = step
    return keyed


def gaps(base_text: str | None, head_text: str | None) -> list[str]:
    """Changed, added or removed steps that the canary does not run."""
    base, head = _steps(base_text), _steps(head_text)
    found = []
    for key in sorted(set(base) | set(head)):
        old, new = base.get(key), head.get(key)
        if old == new:
            continue
        # The canary tests the new version of a step only if it runs it; a
        # removed step is untested only if the canary never ran the old one.
        if new is not None and canary_skips(new):
            found.append(key)
        elif new is None and old is not None and canary_skips(old):
            found.append(f"{key} (removed)")
    return found


def _show(rev: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    base_rev, head_rev = argv[1], argv[2]
    if yaml is None:
        print("PyYAML unavailable, so the canary's step coverage could not be checked")
        return 0
    try:
        found = gaps(_show(base_rev, ACTION), _show(head_rev, ACTION))
    except yaml.YAMLError as exc:
        print(f"{ACTION} could not be parsed ({exc.__class__.__name__})")
        return 0
    for key in found:
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
