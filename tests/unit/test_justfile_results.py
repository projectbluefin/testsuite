"""Contract tests for the Justfile results recipes (issue #871).

The local ``just results`` path must not render a green check for a run with
zero passing scenarios (an all-``undefined`` report), and ``Background:``
elements must not inflate the scenario totals. These tests shell out to
``just`` so the Justfile itself — not only the ``scripts/e2e_summary.py``
helpers it is required to call — is under test. Outside CI they skip when
``just`` is absent; in CI ``unit-tests.yml`` installs a pinned ``just`` and
these tests run (a missing binary must fail the job, not silently skip the
contract). They never touch the default ``/var/tmp/bluefin-results`` root:
``RESULTS_BASE`` is pointed at ``tmp_path`` for every invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Skip only on developer machines without `just`. In CI (`CI` set), unit-tests.yml
# installs a pinned binary; if it were ever missing the tests must run and fail
# rather than skip — otherwise this contract would stop being enforced silently.
pytestmark = pytest.mark.skipif(
    shutil.which("just") is None and os.environ.get("CI", "").lower()
    not in ("1", "true"),
    reason="just is not installed",
)


def _scenario(name: str, status: str) -> dict:
    return {"type": "scenario", "keyword": "Scenario", "name": name, "status": status}


def _background() -> dict:
    return {"type": "background", "keyword": "Background", "name": "", "status": "passed"}


#: The exact defect shape from #871: every scenario ``undefined`` plus a
#: ``Background:`` that the old inline reader counted as a passing scenario.
UNDEFINED_RUN = [
    _background(),
    _scenario("Open Settings via xdg-open", "undefined"),
    _scenario("Launch Files from dock", "undefined"),
    _scenario("Screenshot overview", "undefined"),
]

MIXED_RUN = [
    _background(),
    _scenario("Open Settings via xdg-open", "failed"),
    _scenario("Launch Files from dock", "passed"),
    _scenario("Screenshot overview", "skipped"),
]


def _write_report(base: Path, run: str, suite: str, elements: list[dict]) -> None:
    suite_dir = base / run / suite
    suite_dir.mkdir(parents=True)
    (suite_dir / "results.json").write_text(
        json.dumps([{"elements": elements}]), encoding="utf-8"
    )


def _just(*args: str, results_base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "RESULTS_BASE": str(results_base)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_undefined_run_is_not_rendered_green(tmp_path):
    _write_report(tmp_path, "run-undefined", "smoke", UNDEFINED_RUN)

    proc = _just("results", results_base=tmp_path)

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "⚠️ smoke: 0/3 passed" in out
    assert "✓" not in out
    assert "✅" not in out


def test_backgrounds_do_not_inflate_totals(tmp_path):
    _write_report(tmp_path, "run-mixed", "smoke", MIXED_RUN)

    proc = _just("results", results_base=tmp_path)

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "❌ smoke: 1/3 passed" in out
    # The old inline reader reported this same report as "3/4 passed":
    # one background plus one skipped scenario rendered as passing.
    assert "/4" not in out


def test_results_honours_results_base_override(tmp_path):
    (tmp_path / "other-base" / "run-b").mkdir(parents=True)

    proc = _just("results", results_base=tmp_path / "other-base")

    assert proc.returncode == 0, proc.stderr
    assert "run-b" in proc.stdout


def test_missing_results_base_is_a_hint_not_an_error(tmp_path):
    proc = _just("results", results_base=tmp_path / "missing")

    assert proc.returncode == 0
    assert "(no results yet" in proc.stdout


def test_compare_results_routes_through_the_shared_scenarios_helper(tmp_path):
    _write_report(tmp_path, "run-combined", "smoke", MIXED_RUN)
    _write_report(
        tmp_path,
        "run-combined",
        "vanilla-gnome",
        [
            _scenario("Open Settings via xdg-open", "passed"),
            _scenario("Launch Files from dock", "failed"),
        ],
    )

    proc = _just("compare-results", "run-combined", results_base=tmp_path)

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "=== Smoke vs Vanilla-GNOME comparison: run-combined ===" in out
    assert "2 overlapping scenario(s)" in out
    assert "1 Bluefin regression(s)" in out
