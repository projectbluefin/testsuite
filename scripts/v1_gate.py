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


def _canary_runs(path: str) -> bool:
    path = path.removeprefix("./")
    return path.startswith(CANARY_COVERED_PREFIX) or path in CANARY_COVERED_PATHS


def canary_covers(plan: dict) -> bool:
    """True when the canary runs every path that needs the composite-action lane."""
    action_paths = [
        path for path, lanes in plan.get("reasons", {}).items() if ACTION_LANE in lanes
    ]
    return bool(action_paths) and all(_canary_runs(path) for path in action_paths)


def decide(
    plan: dict,
    ungated: frozenset[str] = UNGATED_SUITES,
    canary_gaps: tuple[str, ...] = (),
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
    canary = bool(composite) and canary_covers(plan) and not canary_gaps
    if canary:
        composite = set()
    # The canary's own suite (tests/gnomeos-canary/) has no e2e.yml lane;
    # the canary workflow is that lane.
    unhosted = set(plan.get("no_hosted_lane", []))
    if CANARY_SUITE in unhosted:
        unhosted.discard(CANARY_SUITE)
        canary = True
    # A PR plan (vm_validation_plan.py --pr) flags the canary itself.
    canary = canary or bool(plan.get("canary"))
    blockers = sorted(composite | unhosted)

    decision = {
        "action": "",
        "suites": ",".join(boot),
        "ungated": ",".join(skipped),
        "reason": "",
        "canary": "true" if canary and not blockers else "false",
    }
    if blockers:
        decision["action"] = "hold"
        decision["suites"] = ""
        decision["reason"] = (
            f"the change needs lanes e2e.yml cannot boot ({', '.join(blockers)}); "
            "validate them by hand, then run this workflow with force"
        )
        if canary_gaps:
            decision["reason"] += (
                "; the GNOME OS canary skips these changed action steps: "
                + ", ".join(canary_gaps)
            )
    elif canary and not boot:
        decision["action"] = "canary"
        decision["reason"] = (
            "the gnome-e2e composite action changed; run the GNOME OS desktop "
            "canary before moving v1"
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
        if canary:
            decision["reason"] += " and run the GNOME OS desktop canary"
        if skipped:
            decision["reason"] += f"; not gated: {', '.join(skipped)} (#706)"
    return decision


def main(argv: list[str]) -> int:
    plan = json.loads(sys.stdin.read())
    # One step per line or comma, from scripts/v1_gate_canary_scope.py.
    raw = os.environ.get("V1_GATE_CANARY_GAPS", "")
    gaps = tuple(g.strip() for g in raw.replace(",", "\n").splitlines() if g.strip())
    for key, value in decide(plan, canary_gaps=gaps).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
