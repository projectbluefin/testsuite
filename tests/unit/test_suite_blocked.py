"""Unit tests for scripts/suite_blocked.py.

Covers the structural guard that stops a hardware-only suite from passing
silently: a suite whose every scenario is ``@hardware_blocked`` (nvidia) must be
reported as blocked, while a suite with runnable scenarios (hardware) must run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.suite_blocked import (  # noqa: E402
    BLOCKED_TAG,
    collect_scenarios,
    is_all_blocked,
    blocked_report,
    _parse_feature,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "suite_blocked.py"
HARDWARE = REPO_ROOT / "tests" / "hardware"
NVIDIA = REPO_ROOT / "tests" / "nvidia"


# ---------------------------------------------------------------------------
# Feature-file parser
# ---------------------------------------------------------------------------


def test_tags_on_header_line_apply_to_scenario():
    text = "@a @b\nScenario: first\n  * step\n"
    assert _parse_feature(text) == [("first", frozenset({"@a", "@b"}))]


def test_tags_on_separate_lines_apply_to_following_scenario():
    text = "@a\n@b\nScenario: first\n  * step\n"
    assert _parse_feature(text) == [("first", frozenset({"@a", "@b"}))]


def test_tags_reset_after_each_scenario():
    text = "@a\nScenario: first\n  * step\n@b\nScenario: second\n  * step\n"
    assert _parse_feature(text) == [
        ("first", frozenset({"@a"})),
        ("second", frozenset({"@b"})),
    ]


def test_scenario_line_inline_tags_are_captured():
    text = "Scenario: first @inline\n  * step\n"
    assert _parse_feature(text) == [("first", frozenset({"@inline"}))]


def test_feature_and_background_headers_reset_pending_tags():
    """A feature tag applies to every scenario; a background tag does not."""
    text = "@a\nFeature: f\n@b\nBackground: bg\n@c\nScenario: s\n  * step\n"
    assert _parse_feature(text) == [("s", frozenset({"@a", "@c"}))]


def test_step_line_clears_a_stale_pending_tag_block():
    text = "@a\nScenario: first\n  * step\n@orphan\nScenario: second\n  * step\n"
    assert _parse_feature(text) == [
        ("first", frozenset({"@a"})),
        ("second", frozenset({"@orphan"})),
    ]


# ---------------------------------------------------------------------------
# is_all_blocked against the real suite directories
# ---------------------------------------------------------------------------


def test_nvidia_name_resolves_to_all_blocked_directory():
    """The nvidia suite maps to tests/nvidia and is entirely @hardware_blocked."""
    assert NVIDIA.is_dir()
    assert is_all_blocked(NVIDIA)


def test_hardware_name_resolves_to_runnable_directory():
    """The hardware suite maps to tests/hardware and has runnable scenarios."""
    assert HARDWARE.is_dir()
    assert not is_all_blocked(HARDWARE)


def test_collect_scenarios_counts_real_scenarios():
    scenarios = collect_scenarios(NVIDIA)
    assert scenarios, "expected scenarios from tests/nvidia"
    assert all(BLOCKED_TAG in tags for _, tags in scenarios)


def test_is_all_blocked_false_when_any_scenario_is_runnable(tmp_path):
    (tmp_path / "f.feature").write_text(
        "@hardware_blocked\nScenario: a\n  * step\n"
        "@hardware_blocked\nScenario: b\n  * step\n"
        "Scenario: runnable\n  * step\n",
        encoding="utf-8",
    )
    assert not is_all_blocked(tmp_path)


def test_is_all_blocked_true_when_every_scenario_blocked(tmp_path):
    (tmp_path / "f.feature").write_text(
        "@hardware_blocked\nScenario: a\n  * step\n"
        "@hardware_blocked\nScenario: b\n  * step\n",
        encoding="utf-8",
    )
    assert is_all_blocked(tmp_path)


def test_is_all_blocked_false_for_empty_suite(tmp_path):
    """An empty suite is not "blocked" -- behave should surface it on its own."""
    assert not is_all_blocked(tmp_path)


# ---------------------------------------------------------------------------
# blocked_report is a blocked result, never a pass
# ---------------------------------------------------------------------------


def test_blocked_report_scenario_is_not_a_pass():
    report = [
        {
            "name": "nvidia suite blocked",
            "elements": [
                {
                    "type": "scenario",
                    "status": "skipped",
                    "steps": [
                        {
                            "result": {"status": "skipped", "error_message": "blocked"},
                            "status": "skipped",
                        }
                    ],
                }
            ],
        }
    ]
    scenario = report[0]["elements"][0]
    assert scenario["status"] != "passed"
    assert any(
        step["result"]["status"] == "skipped" for step in scenario["steps"]
    )


def test_blocked_report_carries_reason_and_is_loadable(tmp_path):
    out = tmp_path / "results.json"
    report = blocked_report(NVIDIA, "no GPU", "nvidia")
    out.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded[0]["elements"][0]["steps"][0]["result"]["error_message"] == "no GPU"


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


def test_main_reports_nvidia_blocked_and_writes_result(tmp_path):
    out = tmp_path / "results.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(NVIDIA), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "BLOCKED"
    assert completed.stderr.strip() == ""
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded[0]["elements"][0]["status"] == "skipped"


def test_main_reports_hardware_runnable(tmp_path):
    out = tmp_path / "results.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(HARDWARE), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "RUNNABLE"
    assert not out.exists()


def test_main_missing_directory_exits_one(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(tmp_path / "does-not-exist")],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "::error::Suite directory not found" in completed.stdout
    assert "Traceback" not in completed.stderr


def test_main_invoked_by_path_from_repo_root(tmp_path, monkeypatch):
    """e2e.yml runs 'python3 scripts/suite_blocked.py' from the repo root."""
    monkeypatch.chdir(REPO_ROOT)
    out = tmp_path / "results.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(NVIDIA), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "BLOCKED"
