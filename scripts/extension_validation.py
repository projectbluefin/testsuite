#!/usr/bin/env python3
"""Mandatory gate for the GNOME developer extension-validation service.

The service boots an official GNOME OS guest, loads the four gnome-extensions-hive
extensions, and runs a qecore/Behave input+AT-SPI scenario. This module decides
whether that run is a genuine pass.

The gate is deliberately stricter than the general e2e headline
(``scripts/e2e_summary.is_success``).  ``is_success`` scores an all-skipped run
green because whole suites legitimately ship only ``@future`` / ``@quarantine``
scenarios.  An extension-validation run proves nothing unless at least one
scenario genuinely passed and nothing errored, so this gate requires
``passed > 0`` and rejects empty, all-skipped, undefined, untested, and
error/hook-error runs (issue #908 acceptance criteria).

See ``docs/skills/ci-ops/e2e-workflow/references/gnome-extensions-validation.md``
for the guest-lane provisioning, inventory, and repeatable commands.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

# Load e2e_summary by file path rather than package import, avoiding PEP 420
# namespace shadowing when invoked from a consumer workspace.
_E2E_SUMMARY_PATH = Path(__file__).resolve().parent / "e2e_summary.py"
_SPEC = importlib.util.spec_from_file_location("e2e_summary", _E2E_SUMMARY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load e2e_summary from {_E2E_SUMMARY_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

SUCCESS_STATUSES: tuple[str, ...] = _MOD.SUCCESS_STATUSES
count_scenarios = _MOD.count_scenarios


def _non_success_counts(counts: dict[str, int]) -> dict[str, int]:
    """Return the non-zero counts for every status that is not a success.

    Derived from :data:`scripts.e2e_summary.SUCCESS_STATUSES` rather than a
    hardcoded failed/undefined/untested/other list, so a status promoted out of
    the ``other`` bucket (or any future behave status) keeps failing this gate
    exactly as ``e2e_summary.is_success`` fails the headline.
    """
    return {
        status: count
        for status, count in counts.items()
        if status not in SUCCESS_STATUSES and count
    }


def is_extension_validation_pass(counts: dict[str, int]) -> bool:
    """Return True only when at least one scenario passed and nothing errored.

    Fails closed for every run type the extension-validation service must never
    mistake for success (issue #908 acceptance):

    * **empty** — no scenarios at all (``passed == 0``)
    * **all-skipped** — every scenario skipped, none passed (``passed == 0``)
    * **undefined / untested** — steps were not implemented
    * **hook-error / failed-boot / error** — any ``error`` or ``hook_error``
      scenario lands in the ``other`` bucket and fails the gate
    * **any other non-success status** — every key outside
      ``e2e_summary.SUCCESS_STATUSES`` must be zero, so a future behave status
      cannot slip past this gate while failing ``e2e_summary.is_success``

    ``skipped`` is allowed alongside a real pass: ``@future`` / image-incompatible
    scenarios are legitimately not run.  This is intentionally stricter than
    ``e2e_summary.is_success``, which scores an all-skipped run green.
    """
    return counts.get("passed", 0) > 0 and not _non_success_counts(counts)


def _tags(element: dict[str, Any]) -> set[str]:
    return {str(tag).removeprefix("@") for tag in element.get("tags") or []}


def mandatory_not_passed(report: list[dict[str, Any]], tag: str) -> tuple[int, list[str]]:
    """Scenarios carrying ``tag`` (on the feature or the scenario) that did not pass.

    The candidate's tag names its mandatory inventory (#909): behave reports
    scenarios outside the ``--tags`` selection as skipped, so every scenario
    the tag covers is in ``results.json`` and each one must have passed. A
    skipped (quarantined, deselected) or missing mandatory scenario fails.
    Returns ``(mandatory count, ["name: status", ...])``.
    """
    tag = tag.removeprefix("@")
    total = 0
    missing: list[str] = []
    for feature in report:
        feature_tags = _tags(feature)
        for element in feature.get("elements") or []:
            if element.get("type") != "scenario":
                continue
            if tag not in feature_tags | _tags(element):
                continue
            total += 1
            if element.get("status") != "passed":
                missing.append(f"{element.get('name', '?')}: {element.get('status')}")
    return total, missing


def gate_report(results_json: Path, require_tag: str | None = None) -> dict[str, Any]:
    """Evaluate the gate for a ``results.json`` and return a readable report.

    With ``require_tag``, every scenario carrying that tag must also have
    passed, and there must be at least one (see :func:`mandatory_not_passed`).

    Returns ``{"passed": bool, "counts": {...}, "reason": str}``. A missing,
    unreadable, or malformed results file fails the gate (``passed: False``) —
    a missing-result or failed-boot run cannot pass the mandatory service gate,
    and it must still report that verdict as JSON rather than traceback.
    """
    if not results_json.is_file():
        return {
            "passed": False,
            "counts": {},
            "reason": f"missing results file: {results_json}",
        }
    try:
        report = json.loads(results_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "passed": False,
            "counts": {},
            "reason": f"unreadable results file {results_json}: {exc}",
        }
    if not isinstance(report, list) or not all(
        isinstance(feature, dict) for feature in report
    ):
        return {
            "passed": False,
            "counts": {},
            "reason": (
                f"malformed results file {results_json}: expected a JSON list of "
                f"feature objects, got {type(report).__name__}"
            ),
        }
    try:
        counts = count_scenarios(report)
    except (AttributeError, TypeError) as exc:
        return {
            "passed": False,
            "counts": {},
            "reason": (
                f"malformed results file {results_json}: expected scenario objects "
                f'under "elements": {exc}'
            ),
        }
    passed = is_extension_validation_pass(counts)
    non_success = _non_success_counts(counts)
    if passed:
        reason = ""
    elif non_success:
        # Checked before the passed == 0 branch so a hook-error / failed-boot run
        # (passed == 0, other > 0) reports the cause the gate exists to catch
        # rather than reading as a benign empty / all-skipped run.
        reason = "non-success scenarios present: " + ", ".join(
            f"{status}={count}" for status, count in sorted(non_success.items())
        )
    else:
        reason = "no scenario passed (empty / all-skipped run)"
    result: dict[str, Any] = {"passed": passed, "counts": counts, "reason": reason}
    if require_tag:
        total, missing = mandatory_not_passed(report, require_tag)
        result["mandatory"] = {"tag": require_tag, "scenarios": total, "not_passed": missing}
        if passed and not total:
            result.update(passed=False, reason=f"no scenario carries the mandatory tag @{require_tag}")
        elif passed and missing:
            result.update(passed=False, reason=f"mandatory @{require_tag} scenarios did not pass: " + "; ".join(missing))
    return result


def main(argv: list[str] | None = None) -> int:
    """Gate a single results.json; exit 0 on pass, 1 otherwise.

    Invoked by the extension-validation service as::

        python3 scripts/extension_validation.py results/results.json [--require-tag TAG]

    The exit code is the gate verdict; the JSON report on stdout is for logs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results_json", type=Path, help="path to behave results.json"
    )
    parser.add_argument(
        "--require-tag",
        help="every scenario carrying this Behave tag must pass (the candidate's inventory)",
    )
    args = parser.parse_args(argv)
    report = gate_report(args.results_json, args.require_tag)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
