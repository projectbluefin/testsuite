#!/usr/bin/env python3
"""Detect e2e suites whose every scenario is @hardware_blocked.

Some e2e suites (nvidia, and any future hardware-only group) contain only
scenarios that need physical hardware the CI VMs lack. Those scenarios are
tagged ``@hardware_blocked``, which ``e2e.yml`` strips from the behave tag
filter, so behave would run zero scenarios and still exit 0 -- a misleading
green pass.

This module answers one question before behave runs: does the selected suite
contain at least one scenario that is *not* ``@hardware_blocked``?

- ``True``  -> the suite can run at least one scenario; run behave normally.
- ``False`` -> every scenario is ``@hardware_blocked`` (or the suite has no
               scenarios); ``e2e.yml`` must emit an explicit blocked result
               instead of a silent green.

Usage:

    suite_blocked.py SUITE_DIR [--REASON text] [--out PATH]

Prints ``BLOCKED`` and writes a synthetic result to ``PATH`` (default
``results/results.json``) when the suite is all-blocked, otherwise prints
``RUNNABLE``. Both cases exit 0 so the caller can branch on the printed token.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_RESULTS = Path("results/results.json")

BLOCKED_TAG = "@hardware_blocked"


def _parse_feature(text: str) -> list[tuple[str, frozenset[str]]]:
    """Yield ``(scenario_name, tags)`` for each scenario in a feature file.

    behave binds a ``@foo`` tag block to the very next element:

    * tags before a ``Feature:`` header apply to *every* scenario in the feature
      (this is how ``@hardware_blocked`` is declared at the top of gpu.feature);
    * tags before a ``Background:`` apply to the background only;
    * tags before a ``Scenario:``/``Example:`` apply to that scenario, combined
      with the feature-level tags.

    Tags on the scenario header line itself are also captured. ``Feature``
    headers reset the pending per-scenario tag set; any step/docstring line does
    too, so a stray tag block never leaks across scenarios.
    """
    scenarios: list[tuple[str, frozenset[str]]] = []
    feature_tags: set[str] = set()
    pending: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Feature:"):
            feature_tags = set(pending)
            pending = set()
            continue
        if line.startswith("Background:"):
            pending = set()
            continue
        if line.startswith("@"):
            for token in line.replace(",", " ").split():
                if token.startswith("@"):
                    pending.add(token)
            continue
        if line.startswith("Scenario") or line.startswith("Example"):
            tags = set(feature_tags) | set(pending)
            for token in line.replace(",", " ").split():
                if token.startswith("@"):
                    tags.add(token)
            name = _scenario_name(line)
            scenarios.append((name, frozenset(tags)))
            pending = set()
            continue
        pending = set()
    return scenarios


def _scenario_name(header: str) -> str:
    """Return the scenario name from a header like ``Scenario: foo @tag``.

    Strips the keyword (``Scenario`` / ``Scenario Outline`` / ``Example``) and
    any inline ``@tag`` tokens, leaving just the name.
    """
    name = header
    for keyword in ("Scenario Outline:", "Scenario:", "Example:"):
        if header.startswith(keyword):
            name = header[len(keyword):]
            break
    else:
        name = header.split(":", 1)[1] if ":" in header else header
    return " ".join(token for token in name.replace(",", " ").split() if not token.startswith("@")).strip()


def collect_scenarios(suite_dir: Path) -> list[tuple[str, frozenset[str]]]:
    """Every scenario across all feature files under ``suite_dir``."""
    scenarios: list[tuple[str, frozenset[str]]] = []
    for path in sorted(suite_dir.glob("**/*.feature")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        scenarios.extend(_parse_feature(text))
    return scenarios


def is_all_blocked(suite_dir: Path) -> bool:
    """``True`` only if the suite has scenarios and every one is ``@hardware_blocked``.

    A suite with no scenarios is not "blocked" -- that is an empty or misnamed
    suite, which behave should surface on its own.
    """
    scenarios = collect_scenarios(suite_dir)
    if not scenarios:
        return False
    return all(BLOCKED_TAG in tags for _, tags in scenarios)


def blocked_report(suite_dir: Path, reason: str, suite_name: str | None = None) -> list[dict]:
    """Build a synthetic behave JSON report marking the suite as blocked.

    The single skipped scenario carries ``reason`` so the job summary shows the
    block and the ``#706`` link instead of a clean green pass.
    """
    name = suite_name or suite_dir.name
    return [
        {
            "keyword": "Feature",
            "name": f"{name} suite blocked",
            "uri": f"{name}.feature",
            "elements": [
                {
                    "keyword": "Scenario",
                    "name": f"{name}-hardware-block",
                    "type": "scenario",
                    "status": "skipped",
                    "steps": [
                        {
                            "keyword": "Given ",
                            "name": "the required hardware is present",
                            "result": {"status": "skipped", "error_message": reason},
                            "status": "skipped",
                        }
                    ],
                }
            ],
        }
    ]


def _default_reason(name: str) -> str:
    return (
        f"Every scenario in the {name} suite requires hardware the CI VM lacks "
        "(see https://github.com/projectbluefin/testsuite/issues/706)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite_dir", type=Path, help="Selected suite directory to inspect")
    parser.add_argument(
        "--reason",
        default=None,
        help="Block reason embedded in the synthetic result (default: #706 message)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_RESULTS,
        help="Where to write the synthetic result (default: results/results.json)",
    )
    args = parser.parse_args(argv)

    if not args.suite_dir.is_dir():
        print(f"::error::Suite directory not found: {args.suite_dir}")
        return 1

    if not is_all_blocked(args.suite_dir):
        print("RUNNABLE")
        return 0

    reason = args.reason or _default_reason(args.suite_dir.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(blocked_report(args.suite_dir, reason), indent=2), encoding="utf-8"
    )
    print("BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
