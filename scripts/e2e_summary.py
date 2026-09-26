#!/usr/bin/env python3
"""Count scenario results for the e2e job summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

#: Statuses behave reports that get their own column in the job summary.
SCENARIO_STATUSES = ("passed", "failed", "skipped", "undefined", "untested")

#: Catch-all bucket. behave also emits ``error`` and ``hook_error``
#: (see ``behave.model.Scenario.compute_status``), and may grow new statuses.
#: Anything not in :data:`SCENARIO_STATUSES` lands here so the explicit sum
#: always equals the true scenario total.
OTHER_STATUS = "other"

COUNTED_STATUSES = (*SCENARIO_STATUSES, OTHER_STATUS)

#: Statuses that represent a deliberate non-run (``@quarantine``/``@pending``/
#: ``@future`` tagged scenarios are skipped by behave).
SUCCESS_STATUSES = ("passed", "skipped")


def load_report(text: str) -> list[dict[str, Any]]:
    """Parse a behave ``results.json`` string, tolerating a crashed file.

    behave's JSON formatter opens the outfile with ``"w"`` and writes the
    closing ``]`` only in its ``close()`` hook; a mid-run crash (before
    ``close``) therefore leaves N complete top-level feature objects with no
    footer and possibly a truncated final object. ``json.loads`` raises
    ``json.JSONDecodeError`` on such input, which would otherwise abort the
    summarise step -- and on the lab pipeline fail the job for the wrong
    reason. This loader returns the parsed array in the normal case, and on a
    decode error salvages every complete top-level feature object so a crashed
    run still yields a partial report instead of nothing.
    """
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = _salvage_partial(text)
    return report if isinstance(report, list) else []


def _salvage_partial(text: str) -> list[dict[str, Any]]:
    """Recover complete top-level feature objects from a truncated file.

    Skips the opening ``[`` and any ```` , ```` separators, then decodes one
    feature object at a time with :meth:`json.JSONDecoder.raw_decode`; the
    first object that does not parse (a truncated tail) stops the salvage, so
    only whole features are returned.
    """
    decoder = json.JSONDecoder()
    pos = 0
    length = len(text)
    report: list[dict[str, Any]] = []
    while pos < length:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            break
        char = text[pos]
        if char == "[" or char == ",":
            pos += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        report.append(obj)
        pos = end
    return report

def count_scenarios(report: list[dict[str, Any]]) -> dict[str, int]:
    """Count scenario statuses, excluding backgrounds.

    Every scenario element is counted exactly once: known statuses under their
    own key, everything else (``error``, ``hook_error``, a missing status, or
    any future behave status) under ``other``.
    """
    counts = {status: 0 for status in COUNTED_STATUSES}
    for feature in report:
        for element in feature.get("elements") or []:
            if element.get("type") != "scenario":
                continue
            status = element.get("status")
            if status in SCENARIO_STATUSES:
                counts[status] += 1
            else:
                counts[OTHER_STATUS] += 1
    return counts


def scenario_statuses(report: list[dict[str, Any]]) -> dict[str, str]:
    """Map scenario name to status, excluding backgrounds.

    Consumers that need per-scenario statuses (``just compare-results``)
    call this instead of keeping a private results.json walker, so the
    ``type == "scenario"`` filter stays a property of this module rather
    than something every reader re-derives.
    """
    statuses: dict[str, str] = {}
    for feature in report:
        for element in feature.get("elements") or []:
            if element.get("type") != "scenario":
                continue
            name = element.get("name")
            if name:
                statuses[name] = element.get("status", "unknown")
    return statuses


def is_success(counts: dict[str, int]) -> bool:
    """Return True only when every counted scenario passed or was skipped.

    ``failed == 0`` is not enough: an undefined-only, untested-only or
    errored run must never render a green headline.
    """
    return all(
        count == 0
        for status, count in counts.items()
        if status not in SUCCESS_STATUSES
    )


def summary_icon(counts: dict[str, int]) -> str:
    """Headline icon: ❌ on failure, ✅ only on a clean run, ⚠️ otherwise."""
    if counts.get("failed"):
        return "❌"
    return "✅" if is_success(counts) else "⚠️"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", type=Path)
    args = parser.parse_args(argv)
    report = load_report(args.results_json.read_text(encoding="utf-8"))
    print(json.dumps(count_scenarios(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
