#!/usr/bin/env python3
"""Tell new failures from failures already present at v1 (testsuite#1027).

When the post-merge gate's ``e2e.yml`` call fails, ``update-v1-tag.yml`` boots
the failed suites again with the tests at the current ``v1`` (the baseline) on
the same image digest, then runs this script over both runs' artifacts.

The gate exists to catch testsuite changes that break the suites, not bugs in
the image under test. So ``v1`` may still move when every candidate failure
also fails at ``v1``. Anything this script cannot explain holds ``v1``
(fail-closed):

- a scenario that fails at the candidate but not at ``v1`` (a regression);
- a suite job that failed with no failing scenario recorded (setup failure,
  missing results, or the #1022 ``assert_passed.py`` verdict);
- a failed candidate suite with no baseline result to compare against.

Artifacts are the ``e2e-metadata-<suffix>-<suite>`` and
``e2e-results-<suffix>-<suite>`` uploads from ``e2e.yml``, where ``<suffix>``
is derived from the image string exactly as ``e2e.yml`` derives it. The
candidate and baseline runs pass differently spelled references to the same
digest, so their suffixes differ.

Usage:
    python3 scripts/v1_gate_compare.py ARTIFACT_DIR CANDIDATE_IMAGE BASELINE_IMAGE [--summary FILE]

Prints ``verdict=move`` or ``verdict=hold`` for ``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FAILED_STATUSES = frozenset({"failed", "error"})


def artifact_suffix(image: str) -> str:
    """Mirror e2e.yml's "Prepare artifact metadata" step."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", image).strip("-").lower()


def failed_scenarios(results: Path) -> set[str] | None:
    """Failed scenarios in a behave JSON report, or None if it is unreadable."""
    try:
        features = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(features, list):
        return None
    failed = set()
    for feature in features:
        for element in feature.get("elements", []):
            if (
                element.get("type") == "scenario"
                and element.get("status") in FAILED_STATUSES
            ):
                failed.add(f"{feature.get('name', '?')} :: {element.get('name', '?')}")
    return failed


def load_side(artifacts: Path, image: str) -> dict[str, tuple[str, set[str] | None]]:
    """Map suite -> (job conclusion, failed scenarios) for one image string."""
    prefix = f"e2e-metadata-{artifact_suffix(image)}-"
    side = {}
    for meta_dir in sorted(artifacts.glob(f"{prefix}*")):
        suite = meta_dir.name[len(prefix) :]
        try:
            meta = json.loads(
                (meta_dir / "e2e-metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            meta = {}
        results = (
            artifacts / f"e2e-results-{artifact_suffix(image)}-{suite}" / "results.json"
        )
        side[suite] = (meta.get("conclusion", "unknown"), failed_scenarios(results))
    return side


def compare(artifacts: Path, candidate_image: str, baseline_image: str) -> dict:
    """Return {"verdict", "problems", "preexisting"} for the two runs."""
    candidate = load_side(artifacts, candidate_image)
    baseline = load_side(artifacts, baseline_image)
    problems: list[str] = []
    preexisting: dict[str, list[str]] = {}
    if not candidate:
        problems.append("no candidate results were found")
    for suite, (conclusion, failed) in sorted(candidate.items()):
        if conclusion == "success":
            continue
        if not failed:
            problems.append(
                f"{suite}: the job failed with no failing scenario recorded "
                "(setup failure, missing results or the assert_passed verdict)"
            )
            continue
        base = baseline.get(suite)
        if base is None or base[1] is None:
            problems.append(f"{suite}: no result at v1 to compare with")
            continue
        new = sorted(failed - base[1])
        if new:
            problems.append(
                f"{suite}: fails at the candidate but not at v1: " + "; ".join(new)
            )
        else:
            preexisting[suite] = sorted(failed)
    return {
        "verdict": "hold" if problems else "move",
        "problems": problems,
        "preexisting": preexisting,
    }


def summary_markdown(result: dict) -> str:
    lines = ["### Candidate failures compared with v1", ""]
    if result["problems"]:
        lines.append("**Not explained by v1:**")
        lines.extend(f"- {p}" for p in result["problems"])
        lines.append("")
    for suite, scenarios in result["preexisting"].items():
        lines.append(f"**{suite}:** {len(scenarios)} failure(s) already present at v1:")
        lines.extend(f"- {s}" for s in scenarios)
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("candidate_image")
    parser.add_argument("baseline_image")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv[1:])
    result = compare(args.artifacts, args.candidate_image, args.baseline_image)
    if args.summary:
        args.summary.write_text(summary_markdown(result), encoding="utf-8")
    print(f"verdict={result['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
