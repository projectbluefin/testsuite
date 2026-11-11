#!/usr/bin/env python3
"""Turn failures the v1 gate accepted as pre-existing into issues for the hive.

When a candidate failure also fails with the tests at ``v1`` on the same image
digest, ``scripts/v1_gate_compare.py`` lets ``v1`` move: the failure comes from
the image (or the VM), not from the merged change. Left alone, such a failure
keeps every later run red, including the PR VM check, until someone notices
it by hand (#1143, #1153). This script writes one issue per failing scenario
so the hive quarantines or fixes it without a person finding it first.

Usage:
    python3 scripts/v1_gate_preexisting.py ARTIFACT_DIR CANDIDATE_IMAGE PREEXISTING_JSON RUN_URL

``PREEXISTING_JSON`` is the ``--preexisting`` file from ``v1_gate_compare.py``
(``{"suite": ["Feature :: Scenario", ...]}``). Prints one JSON object per line,
``{"title", "body", "needs_human"}``. The workflow files each title that has no
open issue yet, so a failure seen on every run is filed once.

More than ``MAX_ISSUES`` scenarios at once is treated as one image-wide
problem (a broken build, a missing package set) and becomes a single issue for
a maintainer, rather than a flood of per-scenario issues. Its title leaves
out the count, so a later run with a different count finds it still open.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# v1_gate_compare.py is a sibling script, not a package. Add this directory so
# the import works both when run as ``python3 scripts/v1_gate_preexisting.py``
# and when imported as a module (pytest).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_gate_compare import FAILED_STATUSES, artifact_suffix  # noqa: E402

MAX_ISSUES = 5
TITLE_LIMIT = 200


def image_name(image: str) -> str:
    """The image without its digest: ghcr.io/org/name:tag@sha256:... -> org/name:tag."""
    name = image.split("@", 1)[0]
    return name.split("/", 1)[1] if name.startswith("ghcr.io/") else name


def image_repo(image: str) -> str:
    """The GitHub repository that builds the image, for ghcr.io images."""
    name = image.split("@", 1)[0]
    if not name.startswith("ghcr.io/"):
        return ""
    path = name[len("ghcr.io/") :].rsplit(":", 1)[0]
    return path if path.count("/") == 1 else ""


def repo_path(location: str) -> str:
    """behave's file:line, relative to the repo.

    Some suites run from a checkout inside the guest and report it as a prefix
    ("bluefin-tests/tests/smoke/...:55"); others report "tests/...".
    """
    if location.startswith("tests/"):
        return location
    at = location.find("/tests/")
    return location[at + 1 :] if at >= 0 else location


def locations(artifacts: Path, image: str, suite: str) -> dict[str, str]:
    """Map "Feature :: Scenario" -> the scenario's file:line from behave's JSON."""
    results = (
        artifacts / f"e2e-results-{artifact_suffix(image)}-{suite}" / "results.json"
    )
    try:
        features = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {}
    for feature in features if isinstance(features, list) else []:
        for element in feature.get("elements", []):
            if (
                element.get("type") == "scenario"
                and element.get("status") in FAILED_STATUSES
            ):
                key = f"{feature.get('name', '?')} :: {element.get('name', '?')}"
                found[key] = repo_path(element.get("location", ""))
    return found


def title_for(image: str, suite: str, scenario: str) -> str:
    title = f"e2e: {suite} fails on {image_name(image)}, also at v1: {scenario}"
    return title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"


def scenario_body(
    image: str, suite: str, scenario: str, location: str, run_url: str
) -> str:
    repo = image_repo(image)
    where = (
        f"`{location}`"
        if location
        else "the feature file (search for the scenario name)"
    )
    image_issue = (
        f"an issue in `{repo}` (a maintainer files it if the hive cannot open issues there)"
        if repo
        else "an issue in the image's own repository (a maintainer files it)"
    )
    return f"""**Summary:** the scenario "{scenario}" in suite `{suite}` fails on `{image}` with the tests at the merged commit **and** with the tests at `v1`, so the post-merge `v1` gate accepted it as a pre-existing failure. Its cause is in the image or the VM, not in a testsuite change. Until it is handled, every run that boots `{suite}` stays red, including the PR VM check.

Filed automatically by the `v1` gate (`.github/workflows/update-v1-tag.yml`, step "File pre-existing failures").

## Evidence

- Scenario: {where}
- Image: `{image}`
- Run: {run_url} (job "Boot merged tests" and job "Boot v1 tests (baseline)", suite `{suite}`). The step summary lists it under "already present at v1"; the failing step and logs are in the `e2e-*` artifacts.

## Ask

1. Find out why it fails on this image: read the scenario's failing step and the journal, screenshot and coredump output in the run's artifacts.
2. Decide:
   - **VM-only** (the VM lacks hardware or a service real machines have): skip it in VMs the way the suite already handles VM-only cases (for example `IGNORED_FAILED_UNITS_IN_VM` in `tests/smoke/features/steps/system_health_steps.py`, or an existing VM tag). Keep it on bare metal.
   - **Image bug** (it would fail on real hardware too): tag the scenario `@quarantine` with a comment naming the cause, the way #1147 did, and say in the PR that a maintainer must file {image_issue}.
   - **Test bug** (the test is wrong for this image): fix the test.
3. Don't raise a timeout to hide it, and don't delete the scenario.

## Acceptance criteria

- This scenario no longer fails in `{suite}` on the current `{image_name(image)}`: skipped in VMs, quarantined or fixed, with the reason next to the scenario. Other failures in the suite have their own issues.

## Test plan

- Unit tests and `behave --dry-run` (AGENTS.md gates).
- The PR VM check boots `{suite}` on the PR; link its run. If it does not run, a maintainer starts `manual.yml` with `suites={suite}` from the fix branch.

## Out of scope

- Changing the image itself, or `.github/workflows/e2e.yml`.
"""


def many_body(image: str, failures: list[tuple[str, str]], run_url: str) -> str:
    listed = "\n".join(f"- `{suite}`: {scenario}" for suite, scenario in failures)
    return f"""**Needs a maintainer:** {len(failures)} scenarios fail on `{image}` with the tests at the merged commit **and** at `v1`. That many at once points at the image as a whole (a broken or stale build, missing packages, a changed desktop), not at single tests, so the `v1` gate filed one issue instead of one per scenario.

Filed automatically by the `v1` gate (`.github/workflows/update-v1-tag.yml`, step "File pre-existing failures").

Run: {run_url}

{listed}

Decide whether the image or the tests need to change. Quarantining all of these would hide a broken image; once the cause is known, file per-scenario issues for what the hive should fix.
"""


def issues(artifacts: Path, image: str, preexisting: dict, run_url: str) -> list[dict]:
    failures = [
        (suite, scenario)
        for suite in sorted(preexisting)
        for scenario in sorted(preexisting[suite])
    ]
    if not failures:
        return []
    if len(failures) > MAX_ISSUES:
        title = f"e2e: many scenarios fail on {image_name(image)}, also at v1"
        return [
            {
                "title": title,
                "body": many_body(image, failures, run_url),
                "needs_human": True,
            }
        ]
    found: dict[str, dict[str, str]] = {}
    out = []
    for suite, scenario in failures:
        if suite not in found:
            found[suite] = locations(artifacts, image, suite)
        out.append(
            {
                "title": title_for(image, suite, scenario),
                "body": scenario_body(
                    image, suite, scenario, found[suite].get(scenario, ""), run_url
                ),
                "needs_human": False,
            }
        )
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    artifacts, image, preexisting_file, run_url = (
        Path(argv[1]),
        argv[2],
        Path(argv[3]),
        argv[4],
    )
    try:
        preexisting = json.loads(preexisting_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        preexisting = {}
    for issue in issues(artifacts, image, preexisting, run_url):
        print(json.dumps(issue))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
