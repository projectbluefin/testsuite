#!/usr/bin/env python3
"""Change-path policy: which candidate-VM suites must a PR boot before v1?

Maps the files a pull request changes to the minimal representative set of
e2e.yml suites that must run against a real candidate image before the change
is distributed to consumers through the managed ``v1`` tag (testsuite#1027).

The policy is fail-closed: a path no rule recognises requires the full
representative set (GUI, SSH and bootc-lifecycle lanes) rather than nothing.
Docs, unit tests and repo-local tooling that never reaches a VM need no boot.

This script only computes the plan. It does not dispatch VMs, set statuses or
change required checks; wiring it into CI is a maintainer decision (#1027).

Usage:
    git diff --name-only BASE...HEAD | python3 scripts/vm_validation_plan.py
    python3 scripts/vm_validation_plan.py tests/smoke/features/steps/x.py

Prints JSON: {"vm_required": bool, "suites": [...], "no_hosted_lane": [...],
"composite_action": [...], "reasons": {path: [suite, ...]}}.

``composite_action`` lists pseudo-lanes for code e2e.yml never executes: the
gnome-e2e composite action and the extension-validation gate it alone runs
(e2e.yml neither uses the action nor sparse-checks-out that script). Booting
e2e.yml suites cannot validate those changes, so they are reported separately
and must be exercised through a workflow that calls the action at the PR ref.
"""

from __future__ import annotations

import fnmatch
import json
import sys

# Representative lanes. GUI exercises GNOME/AT-SPI startup inside the VM,
# SSH exercises runner-side probes, LIFECYCLE exercises bootc reboots.
GUI = "smoke"
SSH = "common"
LIFECYCLE = "lifecycle"
FULL = (GUI, SSH, LIFECYCLE)
# Pseudo-lane: needs a run of the gnome-e2e composite action, not e2e.yml.
ACTION = "gnome-e2e-action"
ACTION_LANES = frozenset({ACTION})

# Suites e2e.yml can boot on hosted runners (its `suites` input).
HOSTED_SUITES = frozenset(
    {
        "smoke",
        "developer",
        "dx",
        "software",
        "vanilla-gnome",
        "bazzite",
        "common",
        "lifecycle",
        "installer",
        "kde-smoke",
        "extensions",
    }
)

# Ordered (glob, suites) rules; first match wins. An empty tuple means the
# path never executes inside a candidate VM.
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Never reach a VM: documentation, unit tests, repo-local tooling.
    ("*.md", ()),
    ("docs/*", ()),
    ("dashboard/*", ()),
    ("argocd/*", ()),
    ("tests/unit/*", ()),
    ("LICENSE", ()),
    ("renovate.json", ()),
    ("codecov.yml", ()),
    ("Justfile", ()),
    ("plans/*", ()),
    (".github/workflows/pr-validate.yml", ()),
    (".github/workflows/unit-tests.yml", ()),
    (".github/workflows/docs-validate.yml", ()),
    (".github/workflows/publish-to-pages.yml", ()),
    (".github/workflows/update-v1-tag.yml", ()),
    ("scripts/validate_docs.py", ()),
    ("scripts/generate_skill_index.py", ()),
    ("scripts/update_coverage_snapshot.py", ()),
    ("scripts/generate_badges.py", ()),
    ("scripts/v1_gate.py", ()),
    ("scripts/v1_gate_compare.py", ()),
    ("scripts/vm_validation_plan.py", ()),
    # Shared helpers: route by the path that imports them.
    ("tests/shared/kde_*", ("kde-smoke",)),
    ("tests/shared/extension_*", ("extensions",)),
    ("tests/shared/gnome_extensions_*", ("extensions",)),
    ("tests/shared/ssh_*", (SSH, LIFECYCLE)),
    ("tests/shared/*", (GUI, SSH)),
    # Runner images and the composed e2e overlay.
    ("container/Containerfile.kde-runner", ("kde-smoke",)),
    ("container/requirements.kde-runner.txt", ("kde-smoke",)),
    ("container/*", (GUI, SSH)),
    (".github/workflows/build-kde-runner.yml", ("kde-smoke",)),
    (".github/workflows/build-runner.yml", (GUI, SSH)),
    # Distributed workflow and composite action.
    (".github/actions/gnome-e2e/*", (ACTION,)),
    (".github/workflows/e2e.yml", FULL),
    (".github/workflows/manual.yml", FULL),
    (".github/workflows/migration-test.yml", (LIFECYCLE,)),
    (".github/workflows/iso-*.yml", ("installer",)),
    # Helper scripts e2e.yml sparse-checks-out and runs per suite.
    ("scripts/install-kde-webdriver.sh", ("kde-smoke",)),
    ("scripts/assert_kde_passed.py", ("kde-smoke",)),
    # Run only inside the gnome-e2e composite action, never by e2e.yml.
    ("scripts/extension_validation.py", (ACTION,)),
    ("scripts/*", (GUI, SSH)),
    ("flatpak-app-list.txt", (GUI, SSH)),
)


def suites_for_path(path: str) -> tuple[str, ...]:
    """Return the suites one changed path requires (fail-closed default)."""
    path = path.strip().removeprefix("./")
    parts = path.split("/")
    # tests/<suite>/** — suite READMEs fall through to the *.md rule first.
    if (
        len(parts) >= 3
        and parts[0] == "tests"
        and parts[1] not in ("shared", "unit")
        and not path.endswith(".md")
    ):
        return (parts[1],)
    for pattern, suites in RULES:
        if fnmatch.fnmatchcase(path, pattern):
            return suites
    return FULL


def plan(paths: list[str]) -> dict:
    """Combine per-path requirements into one minimal plan."""
    reasons: dict[str, list[str]] = {}
    required: set[str] = set()
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        suites = list(suites_for_path(path))
        reasons[path] = suites
        required.update(suites)
    return {
        "vm_required": bool(required),
        "suites": sorted(required & HOSTED_SUITES),
        "no_hosted_lane": sorted(required - HOSTED_SUITES - ACTION_LANES),
        "composite_action": sorted(required & ACTION_LANES),
        "reasons": reasons,
    }


def main(argv: list[str]) -> int:
    paths = argv[1:] if len(argv) > 1 else sys.stdin.read().splitlines()
    print(json.dumps(plan(paths), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
