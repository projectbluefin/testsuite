#!/usr/bin/env python3
"""Mandatory gate for the GNOME developer extension-validation service.

The service boots an official GNOME OS guest, loads the four gnome-extensions-hive
extensions, and runs a qecore/Behave input+AT-SPI scenario. This module decides
whether that run is a genuine pass.

The gate is deliberately stricter than the general e2e headline
(``scripts/e2e_summary.is_success``).  ``is_success`` scores an all-skipped or
empty run green because whole suites legitimately ship only ``@future`` /
``@quarantine`` scenarios.  An extension-validation run proves nothing unless at
least one scenario genuinely passed and nothing errored, so this gate requires
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

SUCCESS_STATUSES: set[str] = _MOD.SUCCESS_STATUSES
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
    ``e2e_summary.is_success``, which scores an all-skipped or empty run green.
    """
    return counts.get("passed", 0) > 0 and not _non_success_counts(counts)


def gate_report(results_json: Path) -> dict[str, Any]:
    """Evaluate the gate for a ``results.json`` and return a readable report.

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
    return {"passed": passed, "counts": counts, "reason": reason}


def main(argv: list[str] | None = None) -> int:
    """Gate a single results.json; exit 0 on pass, 1 otherwise.

    Invoked by the extension-validation service as::

        python3 scripts/extension_validation.py results/results.json

    The exit code is the gate verdict; the JSON report on stdout is for logs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results_json", type=Path, help="path to behave results.json"
    )
    args = parser.parse_args(argv)
    report = gate_report(args.results_json)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
