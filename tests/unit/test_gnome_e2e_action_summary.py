"""Regression guard for the gnome-e2e action's results summary.

The ``Summarise results`` step of ``.github/actions/gnome-e2e/action.yml`` used
to restate scenario counting and decide its headline on ``failed == 0``. A
behave run in which nothing passed — every scenario ``undefined`` (steps not
implemented) or ``untested`` (aborted after a hook error) — therefore rendered

    E2E PASSED: 0 passed / 0 failed / 0 skipped (total 0)

plus a green ``✅ E2E Results`` job summary, while the unit-tested
``scripts/e2e_summary.py`` — the copy ``e2e.yml`` runs — was written to make
exactly that impossible. These tests run the step's *embedded* Python against
synthetic ``results.json`` payloads, so the copy under test is the copy that
ships (projectbluefin/testsuite#797).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
ACTION = REPO_ROOT / ".github" / "actions" / "gnome-e2e" / "action.yml"


def _action_text() -> str:
    return ACTION.read_text(encoding="utf-8")


def _summarise_step() -> str:
    step = _action_text().partition("- name: Summarise results")[2]
    assert step, "Summarise results step not found in the gnome-e2e action"
    return step


def _summarise_script() -> str:
    """The Python heredoc embedded in the action's Summarise results step."""
    step = _summarise_step()
    body = step.partition("python3 - <<'PYEOF'")[2].partition("\n        PYEOF")[0]
    assert body, "Summarise results step no longer embeds a PYEOF script"
    # YAML strips the run-block indentation, so the shipped script starts at
    # column 0 — match that before executing it.
    return textwrap.dedent(body)


def _scenario(status: str) -> dict:
    return {"type": "scenario", "status": status, "name": f"{status} scenario", "steps": []}


def _clean_env(summary_file: Path) -> dict[str, str]:
    """Environment for the step subprocess.

    CI runs pytest under ``coverage`` with ``COVERAGE_PROCESS_START`` set and
    ``[run] patch = subprocess``, which injects measurement into child
    processes; the step under test is not the thing being measured here, so
    strip that (and pytest's) state and keep the run hermetic.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COVERAGE_", "PYTEST_", "PYTHON"))
    }
    env["GNOME_E2E_SUITE"] = "smoke"
    env["GITHUB_STEP_SUMMARY"] = str(summary_file)
    return env


def _run_summary(tmp_path: Path, scenarios: list[str]) -> tuple[str, str]:
    """Run the shipped step script against a synthetic report.

    Returns ``(stdout, job-summary markdown)``.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    report = [{"name": "synthetic feature", "elements": [_scenario(s) for s in scenarios]}]
    (results_dir / "results.json").write_text(json.dumps(report), encoding="utf-8")

    # Stand in for the action's testsuite checkout (`_testsuite`), which the
    # step imports scripts/e2e_summary.py from.
    checkout = tmp_path / "_testsuite"
    checkout.mkdir()
    (checkout / "scripts").symlink_to(REPO_ROOT / "scripts", target_is_directory=True)

    script = tmp_path / "summarise.py"
    script.write_text(_summarise_script(), encoding="utf-8")

    summary_file = tmp_path / "step-summary.md"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=_clean_env(summary_file),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    return completed.stdout, summary


def _run_summary_without_module(tmp_path: Path) -> tuple[str, str]:
    """Same as :func:`_run_summary` but with no ``_testsuite`` checkout."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "results.json").write_text(
        json.dumps([{"name": "f", "elements": [_scenario("passed")]}]), encoding="utf-8"
    )

    script = tmp_path / "summarise.py"
    script.write_text(_summarise_script(), encoding="utf-8")

    summary_file = tmp_path / "step-summary.md"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=_clean_env(summary_file),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    return completed.stdout, summary


# ── The shipped step must not render a green headline for a run with nothing
#    passing ────────────────────────────────────────────────────────────────────


def test_undefined_only_run_is_not_reported_as_passed(tmp_path):
    stdout, summary = _run_summary(tmp_path, ["undefined", "undefined"])

    assert "PASSED" not in stdout
    assert "E2E INCOMPLETE" in stdout
    assert summary.startswith("## ⚠️ E2E Results")
    # Undefined scenarios are counted, and the total includes them (the old
    # copy dropped them entirely and printed "total 0").
    assert "| 0 | **0** | 0 | 2 | 0 | 0 | 2 |" in summary


def test_untested_only_run_is_not_reported_as_passed(tmp_path):
    stdout, summary = _run_summary(tmp_path, ["untested"])

    assert "PASSED" not in stdout
    assert summary.startswith("## ⚠️ E2E Results")


def test_errored_run_with_zero_failures_is_not_reported_as_passed(tmp_path):
    stdout, summary = _run_summary(tmp_path, ["passed", "error", "hook_error"])

    assert "PASSED" not in stdout
    assert summary.startswith("## ⚠️ E2E Results")


def test_all_passed_run_is_still_reported_as_passed(tmp_path):
    stdout, summary = _run_summary(tmp_path, ["passed", "passed", "skipped"])

    assert "E2E PASSED: 2 passed / 0 failed / 1 skipped" in stdout
    assert summary.startswith("## ✅ E2E Results")


def test_failed_run_is_reported_as_failed(tmp_path):
    stdout, summary = _run_summary(tmp_path, ["passed", "failed"])

    assert "E2E FAILED" in stdout
    assert summary.startswith("## ❌ E2E Results")


def test_summary_is_unavailable_rather_than_green_without_the_shared_module(tmp_path):
    """Fail closed: no importable module, no justification for a headline."""
    stdout, summary = _run_summary_without_module(tmp_path)

    assert "ERROR: cannot import scripts.e2e_summary" in stdout
    assert summary.startswith("## ⚠️ E2E Results")


# ── Structural guard: the step must consume the tested module, not restate it ─


def test_step_imports_the_tested_summary_module():
    step = _summarise_step()

    assert "from scripts.e2e_summary import" in step
    for helper in ("count_scenarios", "is_success", "summary_icon"):
        assert helper in step


def test_step_does_not_reimplement_counting_or_the_headline():
    step = _summarise_step()

    assert "def count_scenarios" not in step
    assert "def is_success" not in step
    assert "def summary_icon" not in step
    # The bug was deciding the headline on `failed == 0`.
    assert "if failed == 0" not in step
    assert "is_success(counts)" in step


def test_action_checks_out_the_summary_module():
    """The sparse checkout must include scripts/ or the import cannot resolve."""
    checkout = _action_text().partition("- name: Checkout testsuite")[2].partition("- name:")[0]

    assert checkout, "Checkout testsuite step not found"
    assert "scripts" in checkout
