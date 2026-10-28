#!/usr/bin/env python3
"""Mandatory-coverage verdict gate for the e2e job.

The final CI check historically read only ``behave_rc``. behave exits 0 when
every scenario was skipped/undefined/untested, so a smoke lane whose
``before_all`` setup failed (all scenarios skipped) produced a green job. That
is a false green: nothing was executed, yet qualification passed.

This gate is the verdict contract for the desktop suites in ``e2e.yml`` (KDE
and the smoke/developer/dx/software/vanilla-gnome/bazzite lanes); the ``gnome-e2e``
action does not call it yet (a follow-up). It fails the job when
the run cannot authorize qualification:

- the results file is missing after the run,
- the file is empty or truncated (a crashed lane left a partial ``results.json``),
- or ``passed`` is 0 (every counted scenario was skipped/undefined/untested/error).

A deliberately inapplicable shard (the KDE webdriver stack could not be installed
and the suite was skipped with an explicit reason) is a passing terminal state:
it is not a product failure, so ``--skip-reason`` authorizes qualification. A
runnable suite that silently self-disabled every scenario is distinct and still
fails via the ``passed == 0`` check.

Optional documented skips stay visible in the job summary and never fail this
gate on their own; a run with at least one genuinely passing scenario is
qualified. Infrastructure failure (image never booted, no results at all) is
distinct from a product failure but still blocks qualification, so both fail
here.

Built on :mod:`scripts.e2e_summary` so the status tallies and the
truncation-tolerant parser are defined once, not duplicated in YAML or a second
script.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

# Load e2e_summary by file path rather than `from scripts.e2e_summary import`,
# mirroring scripts/extension_validation.py. A plain package import only works
# when the repo root is on sys.path, and a consumer's regular `scripts/` package
# (one with __init__.py) would shadow the testsuite namespace portion; loading
# by path is the single, shadow-free way to reach the tested implementation.
_E2E_SUMMARY_PATH = Path(__file__).resolve().parent / "e2e_summary.py"
try:
    _e2e_summary_spec = importlib.util.spec_from_file_location(
        "e2e_summary", _E2E_SUMMARY_PATH
    )
    assert _e2e_summary_spec is not None and _e2e_summary_spec.loader is not None
    _e2e_summary = importlib.util.module_from_spec(_e2e_summary_spec)
    _e2e_summary_spec.loader.exec_module(_e2e_summary)
    count_scenarios = _e2e_summary.count_scenarios
    load_report = _e2e_summary.load_report
except Exception as exc:  # pragma: no cover - defensive, mirrors extension_validation.py
    raise SystemExit(
        f"ERROR: cannot load scripts/e2e_summary.py: "
        f"{type(exc).__name__}: {exc}"
    ) from exc

DEFAULT_RESULTS = Path("results") / "results.json"
DEFAULT_FAILED_SETUP_MARKER = Path("results") / "failed_setup.txt"


def _fail(message: str) -> int:
    """Emit a GitHub Actions error annotation and exit 1."""
    print(f"::error::{message}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results_json",
        type=Path,
        nargs="?",
        default=DEFAULT_RESULTS,
        help="Path to the behave results.json (default: results/results.json)",
    )
    parser.add_argument(
        "--failed-setup-marker",
        default=DEFAULT_FAILED_SETUP_MARKER,
        type=Path,
        help="Path to the failed_setup marker file (default: results/failed_setup.txt)",
    )
    parser.add_argument(
        "--skip-reason",
        default="",
        help=(
            "Optional reason a mandatory shard was deliberately inapplicable "
            "(e.g. the KDE webdriver stack could not be installed). A non-empty "
            "value is a passing terminal state for the gate: an inapplicable "
            "shard is not a product failure. An empty value keeps the "
            "fail-closed checks below. Do not use this to exempt a runnable "
            "suite that merely skipped every scenario."
        ),
    )
    parser.add_argument(
        "--allow-all-skipped",
        action="store_true",
        help=(
            "Treat a complete report in which every scenario was skipped as a "
            "pass. Only for a shard whose scenarios legitimately all skip on "
            "some images (smoke-firefox on a Flatpak-only-Firefox image, #924). "
            "A setup failure, a missing or truncated report, or any "
            "failed/undefined/untested scenario still fails."
        ),
    )
    args = parser.parse_args(argv)

    # A before_all/setup failure writes this marker and then every scenario is
    # skipped; behave exits 0. It is the primary false-green signal, so check it
    # first and fail closed regardless of what results.json contains.
    if args.failed_setup_marker.is_file():
        return _fail(
            f"Harness before_all setup failed ({args.failed_setup_marker}); "
            "all scenarios were skipped and qualification must not pass"
        )

    # A deliberately inapplicable shard (e.g. KDE webdriver stack could not be
    # installed) is a passing terminal state: it is not a product failure and
    # must not block qualification. This is distinct from a runnable suite that
    # silently self-disabled every scenario, which the passed==0 check below
    # still fails.
    if args.skip_reason:
        print(f"PASS: suite deliberately inapplicable ({args.skip_reason}); no mandatory coverage required")
        return 0

    path = args.results_json
    if not path.is_file():
        return _fail(f"No results.json found after suite run at {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _fail(f"Could not read results.json at {path}: {exc}")

    if not text.strip():
        return _fail(f"results.json at {path} is empty; suite produced no output")

    report, complete = load_report(text)
    try:
        counts = count_scenarios(report)
    except (AttributeError, TypeError):
        # A corrupt report (a non-dict feature/element) raises here, exactly as
        # it does for the mandatory-service-gate in extension_validation.py.
        # A malformed results file cannot authorize qualification, so fail
        # closed on zero passing rather than traceback.
        counts = {status: 0 for status in _e2e_summary.COUNTED_STATUSES}
    passed = counts["passed"]

    print(
        "Mandatory coverage: "
        f"passed={passed} failed={counts['failed']} "
        f"skipped={counts['skipped']} undefined={counts['undefined']} "
        f"untested={counts['untested']} other={counts['other']}"
    )

    if not complete:
        return _fail(
            "results.json is incomplete or truncated; a crashed lane cannot "
            "authorize qualification"
        )
    if (
        args.allow_all_skipped
        and counts["skipped"] > 0
        and sum(counts.values()) == counts["skipped"]
    ):
        print("PASS: every scenario was skipped and this shard allows that")
        return 0
    if passed == 0:
        return _fail(
            "suite reported 0 passing scenarios; skipped/undefined/untested runs "
            "do not establish required coverage"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
