#!/usr/bin/env python3
"""Decide what the post-merge v1 gate does with one main commit (testsuite#1027).

``update-v1-tag.yml`` runs ``scripts/vm_validation_plan.py`` on everything
between the current ``v1`` tag and the merged commit, then pipes that plan here.
This script turns the plan into one of four actions:

- ``move``: nothing in the range reaches a VM; move ``v1`` straight away.
- ``gate``: boot the listed ``e2e.yml`` suites first; move ``v1`` only if
  every suite passes (the #1022 fail-closed verdict inside ``e2e.yml``).
- ``canary``: every change ``e2e.yml`` cannot boot is one the GNOME OS
  desktop canary runs: the gnome-e2e composite action
  (``.github/actions/gnome-e2e/``) outside steps that skip the canary suite,
  ``scripts/extension_validation.py``, or the canary's own suite. Run the
  canary and move ``v1`` only if it passes. With suites to boot as well, the
  action is ``gate`` and ``canary=true``: both must pass.
- ``hold``: the plan needs a lane neither can cover: an action-lane script or
  step the canary skips (``scripts/assert_passed.py``, or a changed step whose
  ``if:`` excludes the canary suite, from ``scripts/v1_gate_canary_scope.py``),
  or a suite with no hosted lane. Keep ``v1`` where it is and alert; a
  maintainer validates by hand and moves it with the workflow's manual
  ``force`` run.

Suites in ``UNGATED_SUITES`` are left out of the boot because they cannot pass
on a single image yet: every ``lifecycle`` upgrade scenario needs a second,
newer image to upgrade to (#706, #1023), and on one image ``bootc upgrade`` is
a no-op that #1039 now fails on purpose. They are reported, never dropped
silently.

Usage:
    python3 scripts/vm_validation_plan.py < paths | python3 scripts/v1_gate.py

Prints ``key=value`` lines for ``$GITHUB_OUTPUT``: action, suites, ungated,
reason, canary.
"""

from __future__ import annotations

import json
import os
import sys

# Requested by the plan but not booted by the gate (see the module docstring).
UNGATED_SUITES = frozenset({"lifecycle"})

# Composite-action-lane paths a GNOME OS canary run exercises: the action
# itself (steps the canary skips are caught by scripts/v1_gate_canary_scope.py)
# and scripts/extension_validation.py, which the action runs for the canary
# suite. Other action-lane paths, such as scripts/assert_passed.py (its step
# skips the canary suite), still hold.
CANARY_COVERED_PREFIX = ".github/actions/gnome-e2e/"
CANARY_COVERED_PATHS = frozenset({"scripts/extension_validation.py"})
ACTION_LANE = "gnome-e2e-action"
CANARY_SUITE = "gnomeos-canary"

# Action-lane paths an extension-validation.yml run exercises (#1218): it
# builds and stages a candidate (#909) and runs the action with
# suite=extensions, so the staging code, the extension suite and its shared
# helpers run there and nowhere else.
EXTENSIONS_COVERED_PREFIXES = (
    "tests/extensions/",
    "tests/shared/extension_",
    "tests/shared/gnome_extensions_",
)
EXTENSIONS_COVERED_PATHS = frozenset(
    {
        "scripts/build_extension_artifact.py",
        "scripts/stage_extension.py",
        "scripts/extension_validation.py",
        ".github/workflows/extension-validation.yml",
    }
)


def _canary_runs(path: str) -> bool:
    path = path.removeprefix("./")
    return path.startswith(CANARY_COVERED_PREFIX) or path in CANARY_COVERED_PATHS


def _extensions_run(path: str) -> bool:
    path = path.removeprefix("./")
    return path.startswith(EXTENSIONS_COVERED_PREFIXES) or path in EXTENSIONS_COVERED_PATHS


def _action_paths(plan: dict) -> list[str]:
    return [path for path, lanes in plan.get("reasons", {}).items() if ACTION_LANE in lanes]


def canary_covers(plan: dict) -> bool:
    """True when the canary runs every path that needs the composite-action lane."""
    action_paths = _action_paths(plan)
    return bool(action_paths) and all(_canary_runs(path) for path in action_paths)


def lanes_needed(
    plan: dict,
    canary_gaps: tuple[str, ...] = (),
    extension_gaps: tuple[str, ...] | None = None,
) -> tuple[bool, bool, bool]:
    """(covered, run canary, run extension validation) for the action lane.

    The canary covers the action and extension_validation.py; an
    extension-validation run covers the staging code and the extension suite.
    ``canary_gaps`` are changed action steps the canary skips;
    ``extension_gaps`` the ones neither the canary nor an extension run
    executes (``v1_gate_canary_scope.py --with-extensions``). Without
    ``extension_gaps`` the extension run is never trusted with a step.
    """
    paths = _action_paths(plan)
    if not paths:
        return False, False, False
    canary = any(_canary_runs(path) for path in paths)
    extensions = any(_extensions_run(path) and not _canary_runs(path) for path in paths)
    remaining = canary_gaps
    if canary_gaps and extension_gaps is not None and len(extension_gaps) < len(canary_gaps):
        # Steps only the extension suite runs are covered by running it.
        extensions = True
        remaining = extension_gaps
    elif extensions and extension_gaps is not None:
        remaining = extension_gaps
    covered = all(_canary_runs(p) or _extensions_run(p) for p in paths) and not remaining
    return covered, canary, extensions


def decide(
    plan: dict,
    ungated: frozenset[str] = UNGATED_SUITES,
    canary_gaps: tuple[str, ...] = (),
    extension_gaps: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Return the gate decision for one validation plan.

    ``canary_gaps`` lists changed action steps the canary skips
    (scripts/v1_gate_canary_scope.py); any of them keeps the action lane a
    blocker, because a canary pass would not have run them.
    """
    requested = list(plan.get("suites", []))
    boot = [s for s in requested if s not in ungated]
    skipped = [s for s in requested if s in ungated]
    composite = set(plan.get("composite_action", []))
    covered, canary, extensions = lanes_needed(plan, canary_gaps, extension_gaps)
    covered = covered and bool(composite)
    if covered:
        composite = set()
    else:
        canary = extensions = False
    # The canary's own suite (tests/gnomeos-canary/) has no e2e.yml lane;
    # the canary workflow is that lane.
    unhosted = set(plan.get("no_hosted_lane", []))
    if CANARY_SUITE in unhosted:
        unhosted.discard(CANARY_SUITE)
        canary = True
    # A PR plan (vm_validation_plan.py --pr) flags the canary itself.
    canary = canary or bool(plan.get("canary"))
    blockers = sorted(composite | unhosted)
    gaps = extension_gaps if extensions and extension_gaps is not None else canary_gaps

    decision = {
        "action": "",
        "suites": ",".join(boot),
        "ungated": ",".join(skipped),
        "reason": "",
        "canary": "true" if canary and not blockers else "false",
        "extensions": "true" if extensions and not blockers else "false",
    }
    runs = [
        name
        for name, needed in (
            ("the GNOME OS desktop canary", canary),
            ("extension validation", extensions),
        )
        if needed
    ]
    if blockers:
        decision["action"] = "hold"
        decision["suites"] = ""
        decision["reason"] = (
            f"the change needs lanes e2e.yml cannot boot ({', '.join(blockers)}); "
            "validate them by hand, then run this workflow with force"
        )
        if gaps:
            decision["reason"] += (
                "; no GNOME OS run the gate makes executes these changed action steps: "
                + ", ".join(gaps)
            )
    elif runs and not boot:
        decision["action"] = "canary"
        decision["reason"] = (
            "the gnome-e2e action lane changed; run " + " and ".join(runs) + " before moving v1"
        )
        if skipped:
            decision["reason"] += f"; not gated: {', '.join(skipped)} (#706)"
    elif not plan.get("vm_required"):
        decision["action"] = "move"
        decision["reason"] = "no changed path reaches a VM"
    elif not boot:
        decision["action"] = "move"
        decision["reason"] = (
            f"only ungated suites were requested ({', '.join(skipped)}); "
            "they need a second image before the gate can boot them (#706)"
        )
    else:
        decision["action"] = "gate"
        decision["reason"] = f"boot {', '.join(boot)} before moving v1"
        if runs:
            decision["reason"] += " and run " + " and ".join(runs)
        if skipped:
            decision["reason"] += f"; not gated: {', '.join(skipped)} (#706)"
    return decision


def main(argv: list[str]) -> int:
    plan = json.loads(sys.stdin.read())
    # One step per line or comma, from scripts/v1_gate_canary_scope.py.
    raw = os.environ.get("V1_GATE_CANARY_GAPS", "")
    gaps = tuple(g.strip() for g in raw.replace(",", "\n").splitlines() if g.strip())
    # Unset (an older caller) means the extension run covers no action step.
    ext_raw = os.environ.get("V1_GATE_EXTENSION_GAPS")
    ext_gaps = None
    if ext_raw is not None:
        ext_gaps = tuple(g.strip() for g in ext_raw.replace(",", "\n").splitlines() if g.strip())
    for key, value in decide(plan, canary_gaps=gaps, extension_gaps=ext_gaps).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
