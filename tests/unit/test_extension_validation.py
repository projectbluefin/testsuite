"""Unit tests for :mod:`scripts.extension_validation`.

Covers the mandatory service gate (issue #908): empty, all-skipped, undefined,
untested, hook-error, failed-boot, and missing-result runs must not pass, while
a run with at least one genuine pass (plus legitimate skips) does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import e2e_summary
from scripts.extension_validation import (
    gate_report,
    is_extension_validation_pass,
    main,
)


def _feature_json(statuses: list[str]) -> str:
    """Serialise a behave results.json: a list of feature dicts with elements."""
    return json.dumps(
        [{"elements": [{"type": "scenario", "status": s} for s in statuses]}]
    )


@pytest.mark.parametrize(
    "counts,expected",
    [
        # acceptance: empty / all-skipped -> no genuine pass
        ({}, False),
        ({"skipped": 5}, False),
        ({"passed": 0, "skipped": 3}, False),
        # acceptance: undefined / untested must fail
        ({"passed": 1, "undefined": 1}, False),
        ({"passed": 1, "untested": 1}, False),
        # acceptance: hook-error / failed-boot / error land in "other"
        ({"passed": 1, "other": 1}, False),
        ({"passed": 1, "failed": 1}, False),
        # genuine pass with legitimate skips -> green
        ({"passed": 1}, True),
        ({"passed": 3, "skipped": 9}, True),
        # a full Bluefin-style spread still needs >=1 pass and no errors
        ({"passed": 2, "failed": 1, "skipped": 4, "other": 0}, False),
        ({"passed": 2, "failed": 0, "skipped": 4, "other": 0}, True),
    ],
)
def test_is_extension_validation_pass(counts: dict[str, int], expected: bool) -> None:
    assert is_extension_validation_pass(counts) is expected


def test_gate_requires_genuine_pass_not_just_skips() -> None:
    # is_success treats all-skipped as green; the service gate must not.
    assert not is_extension_validation_pass({"skipped": 12})
    assert is_extension_validation_pass({"passed": 1, "skipped": 12})


def test_missing_results_file_fails_gate(tmp_path: Path) -> None:
    report = gate_report(tmp_path / "does-not-exist.json")
    assert report["passed"] is False
    assert report["counts"] == {}
    assert "missing results file" in report["reason"]


def test_unreadable_results_file_fails_gate(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    report = gate_report(bad)
    assert report["passed"] is False
    assert "unreadable" in report["reason"]


def test_gate_report_passes_on_genuine_run(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(_feature_json(["passed", "skipped"]), encoding="utf-8")
    report = gate_report(results)
    assert report["passed"] is True
    assert report["reason"] == ""
    assert report["counts"]["passed"] >= 1


def test_gate_report_fails_on_all_skipped(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(_feature_json(["skipped"]), encoding="utf-8")
    report = gate_report(results)
    assert report["passed"] is False
    assert "empty / all-skipped" in report["reason"]


def test_main_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "results.json"
    good.write_text(_feature_json(["passed"]), encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(_feature_json([]), encoding="utf-8")

    assert main([str(good)]) == 0
    assert main([str(empty)]) == 1
    assert main([str(tmp_path / "nope.json")]) == 1


@pytest.mark.parametrize("payload", ['{"features": []}', '"done"', "42", "null"])
def test_non_list_results_file_fails_gate_with_report(
    tmp_path: Path, payload: str
) -> None:
    results = tmp_path / "results.json"
    results.write_text(payload, encoding="utf-8")
    report = gate_report(results)
    assert report["passed"] is False
    assert "malformed" in report["reason"]
    assert main([str(results)]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        '[{"elements": ["scenario"]}]',
        '[{"elements": [null]}]',
        '[{"elements": [["type", "scenario"]]}]',
    ],
)
def test_non_dict_scenario_elements_fail_gate_with_report(
    tmp_path: Path, payload: str
) -> None:
    """Non-dict ``elements`` entries report JSON, not an AttributeError traceback."""
    results = tmp_path / "results.json"
    results.write_text(payload, encoding="utf-8")
    report = gate_report(results)
    assert report["passed"] is False
    assert "malformed" in report["reason"]
    assert main([str(results)]) == 1


def test_hook_error_run_reason_names_the_error(tmp_path: Path) -> None:
    """A hook-error / failed-boot run must not read as an empty/all-skipped run."""
    results = tmp_path / "results.json"
    results.write_text(_feature_json(["hook_error", "skipped"]), encoding="utf-8")
    report = gate_report(results)
    assert report["passed"] is False
    assert "other=1" in report["reason"]
    assert "empty / all-skipped" not in report["reason"]


def test_unknown_non_success_status_fails_gate() -> None:
    """A status promoted out of ``other`` must not bypass the gate.

    ``e2e_summary.is_success`` fails any key outside ``SUCCESS_STATUSES``; this
    gate derives its non-success set the same way instead of hardcoding
    failed/undefined/untested/other, so growing ``SCENARIO_STATUSES`` cannot make
    the gate greener than the headline.
    """
    counts = {"passed": 3, "skipped": 1, "error": 1}
    assert e2e_summary.is_success(counts) is False
    assert is_extension_validation_pass(counts) is False
    assert is_extension_validation_pass({"passed": 3, "skipped": 1, "error": 0}) is True


@pytest.mark.parametrize(
    "statuses,expected_pass,expected_code",
    [(["passed", "skipped"], True, 0), (["passed", "failed"], False, 1)],
)
def test_cli_reports_from_consumer_with_regular_scripts_package(
    tmp_path: Path, statuses: list[str], expected_pass: bool, expected_code: int
) -> None:
    """A consumer's regular scripts package must not hide the sibling helper."""
    consumer = tmp_path / "consumer"
    package = consumer / "scripts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        'raise AssertionError("consumer scripts package imported")\n',
        encoding="utf-8",
    )
    results = consumer / "results.json"
    results.write_text(_feature_json(statuses), encoding="utf-8")
    checkout = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    # Expose both checkouts as in the action; a regular package wins over a
    # namespace package even when the testsuite root comes first.
    env["PYTHONPATH"] = os.pathsep.join((str(checkout), str(consumer)))
    completed = subprocess.run(
        [sys.executable, str(checkout / "scripts/extension_validation.py"), str(results)],
        cwd=consumer,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == expected_code, completed.stderr
    assert completed.stderr == ""
    report = json.loads(completed.stdout)
    assert report["passed"] is expected_pass
    assert report["counts"] == {
        status: statuses.count(status)
        for status in ("passed", "failed", "skipped", "undefined", "untested", "other")
    }
    if expected_pass:
        assert report["reason"] == ""
    else:
        assert "failed=1" in report["reason"]


# ── required tags (#909: staged candidates' mandatory inventory) ──────────


def _tagged_report(statuses: dict[str, str], feature_tags=("just_perfection",)) -> list:
    return [
        {
            "name": "Just Perfection",
            "tags": list(feature_tags),
            "elements": [
                {"type": "scenario", "name": name, "status": status, "tags": []}
                for name, status in statuses.items()
            ],
        },
        {
            "name": "Lifecycle",
            "tags": ["extensions_suite"],
            "elements": [
                {"type": "scenario", "name": "lifecycle jp", "status": "passed",
                 "tags": ["just_perfection"]},
                {"type": "scenario", "name": "lifecycle gold", "status": "skipped",
                 "tags": ["sjc_gold"]},
            ],
        },
    ]


def _write(tmp_path: Path, report) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report))
    return path


def test_required_tag_passes_when_every_tagged_scenario_passed(tmp_path: Path) -> None:
    path = _write(tmp_path, _tagged_report({"panel": "passed", "dash": "passed"}))
    report = gate_report(path, ("just_perfection",))
    assert report["passed"] is True, report


def test_required_tag_fails_on_a_skipped_tagged_scenario(tmp_path: Path) -> None:
    path = _write(tmp_path, _tagged_report({"panel": "passed", "dash": "skipped"}))
    report = gate_report(path, ("just_perfection",))
    assert report["passed"] is False
    assert "'dash' is skipped" in report["reason"]
    # Without the requirement the same run passes: skips are allowed.
    assert gate_report(path)["passed"] is True


def test_required_tag_with_no_scenarios_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, _tagged_report({"panel": "passed"}))
    report = gate_report(path, ("stock_market",))
    assert report["passed"] is False
    assert "no scenario carries the required tag @stock_market" in report["reason"]


def test_required_tag_reads_scenario_tags_with_or_without_at(tmp_path: Path) -> None:
    data = _tagged_report({"panel": "passed"}, feature_tags=())
    data[1]["elements"][0]["tags"] = ["@just_perfection"]
    report = gate_report(_write(tmp_path, data), ("just_perfection",))
    # The feature lost its tag, so only the lifecycle scenario is selected.
    assert report["passed"] is True


def test_require_tag_cli_flag(tmp_path: Path) -> None:
    path = _write(tmp_path, _tagged_report({"panel": "failed"}))
    from scripts.extension_validation import main
    assert main([str(path), "--require-tag", "just_perfection"]) == 1
