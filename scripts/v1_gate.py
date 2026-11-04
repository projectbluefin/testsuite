#!/usr/bin/env python3
"""Decide what the post-merge v1 gate does with one main commit (testsuite#1027).

``update-v1-tag.yml`` runs ``scripts/vm_validation_plan.py`` on everything
between the current ``v1`` tag and the merged commit, then pipes that plan here.
This script turns the plan into one of three actions:

- ``move``: nothing in the range reaches a VM; move ``v1`` straight away.
- ``gate``: boot the listed ``e2e.yml`` suites first; move ``v1`` only if
  every suite passes (the #1022 fail-closed verdict inside ``e2e.yml``).
- ``hold``: the plan needs a lane ``e2e.yml`` cannot boot (the gnome-e2e
  composite action, or a suite with no hosted lane). Keep ``v1`` where it is
  and alert; a maintainer validates by hand and moves it with the workflow's
  manual ``force`` run.

Suites in ``UNGATED_SUITES`` are left out of the boot because they cannot pass
on a single image yet: every ``lifecycle`` upgrade scenario needs a second,
newer image to upgrade to (#706, #1023), and on one image ``bootc upgrade`` is
a no-op that #1039 now fails on purpose. They are reported, never dropped
silently.

Usage:
    python3 scripts/vm_validation_plan.py < paths | python3 scripts/v1_gate.py

Prints ``key=value`` lines for ``$GITHUB_OUTPUT``: action, suites, ungated,
reason.
"""

from __future__ import annotations

import json
import sys

# Requested by the plan but not booted by the gate (see the module docstring).
UNGATED_SUITES = frozenset({"lifecycle"})


def decide(plan: dict, ungated: frozenset[str] = UNGATED_SUITES) -> dict[str, str]:
    """Return the gate decision for one validation plan."""
    requested = list(plan.get("suites", []))
    boot = [s for s in requested if s not in ungated]
    skipped = [s for s in requested if s in ungated]
    blockers = sorted(
        set(plan.get("composite_action", [])) | set(plan.get("no_hosted_lane", []))
    )

    decision = {
        "action": "",
        "suites": ",".join(boot),
        "ungated": ",".join(skipped),
        "reason": "",
    }
    if blockers:
        decision["action"] = "hold"
        decision["suites"] = ""
        decision["reason"] = (
            f"the change needs lanes e2e.yml cannot boot ({', '.join(blockers)}); "
            "validate them by hand, then run this workflow with force"
        )
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
        if skipped:
            decision["reason"] += f"; not gated: {', '.join(skipped)} (#706)"
    return decision


def main(argv: list[str]) -> int:
    plan = json.loads(sys.stdin.read())
    for key, value in decide(plan).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
