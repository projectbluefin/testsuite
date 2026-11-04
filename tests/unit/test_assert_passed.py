"""Unit tests for scripts/assert_passed.py.

The gate is the single authoritative verdict contract that prevents a false
green: a suite run where behave exits 0 but every scenario was
skipped/undefined/untested, or where ``results.json`` is missing, empty, or
truncated. These tests lock in that only ``status == 'passed'`` scenarios count
as coverage and that an incomplete report never qualifies a candidate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.assert_passed import main  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "assert_passed.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scenario(name: str, status: str) -> dict:
    return {"type": "scenario", "name": name, "status": status}


def _report(*statuses: str) -> list[dict]:
    return [
        {
            "name": "suite smoke",
            "elements": [
                _scenario(f"scenario {index}", status)
                for index, status in enumerate(statuses)
            ],
        }
    ]


def _write(tmp_path: Path, report) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _write_text(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "results.json"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Exit-code behaviour
# ---------------------------------------------------------------------------


def test_all_passed_exits_zero(tmp_path, capsys):
    path = _write(tmp_path, _report("passed", "passed", "passed"))
    assert main([str(path)]) == 0
    assert "passed=3" in capsys.readouterr().out


def test_no_scenarios_at_all_exits_one(tmp_path, capsys):
    path = _write(tmp_path, [])
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "passed=0" in out
    assert "0 passing scenarios" in out


def test_all_skipped_exits_one(tmp_path, capsys):
    path = _write(tmp_path, _report("skipped", "skipped"))
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "passed=0" in out
    assert "skipped=2" in out
    assert "0 passing scenarios" in out


def test_all_undefined_exits_one(tmp_path, capsys):
    """The original false-green bug: undefined must never score as passing."""
    path = _write(tmp_path, _report("undefined", "undefined", "undefined"))
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "passed=0" in out
    assert "undefined=3" in out
    assert "0 passing scenarios" in out


def test_all_untested_exits_one(tmp_path, capsys):
    path = _write(tmp_path, _report("untested", "untested"))
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "untested=2" in out
    assert "0 passing scenarios" in out


def test_errored_run_exits_one(tmp_path, capsys):
    """behave 1.3.3 emits error/hook_error; neither is passing coverage."""
    path = _write(tmp_path, _report("error", "hook_error"))
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "other=2" in out
    assert "0 passing scenarios" in out


def test_mixed_passed_and_failed_exits_zero(tmp_path, capsys):
    """behave_rc gates real failures; this gate only asserts passed > 0."""
    path = _write(tmp_path, _report("passed", "failed", "skipped"))
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "passed=1 failed=1" in out


def test_backgrounds_are_not_counted_as_passed(tmp_path, capsys):
    report = [
        {
            "name": "suite smoke",
            "elements": [
                {"type": "background", "name": "Shared setup", "status": "passed"},
                _scenario("real scenario", "passed"),
            ],
        }
    ]
    path = _write(tmp_path, report)
    assert main([str(path)]) == 0
    assert "passed=1" in capsys.readouterr().out


def test_only_backgrounds_exits_one(tmp_path, capsys):
    report = [
        {
            "name": "suite smoke",
            "elements": [
                {"type": "background", "name": "Setup A", "status": "passed"},
                {"type": "background", "name": "Setup B", "status": "passed"},
            ],
        }
    ]
    path = _write(tmp_path, report)
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "passed=0" in out
    assert "0 passing scenarios" in out


# ---------------------------------------------------------------------------
# Deliberate inapplicability (--skip-reason)
#
# A deliberately inapplicable mandatory shard (e.g. the KDE webdriver stack
# could not be installed) is a passing terminal state for the gate: it is not a
# product failure and must not block qualification. This is distinct from a
# runnable suite that silently self-disabled every scenario, which still fails
# via the passed==0 check.
# ---------------------------------------------------------------------------


def test_deliberate_skip_passes_even_with_zero_passing(tmp_path, capsys):
    """0 passing scenarios, but an explicit inapplicability reason is a pass."""
    path = _write(tmp_path, _report("skipped"))
    assert main([str(path), "--skip-reason", "Plasma below 5.27"]) == 0
    out = capsys.readouterr().out
    assert "deliberately inapplicable" in out
    assert "Plasma below 5.27" in out
    assert "0 passing scenarios" not in out


def test_deliberate_skip_passes_without_any_results_file(tmp_path, capsys):
    """The marker authorizes the gate before the results.json is even read."""
    missing = tmp_path / "does-not-exist.json"
    assert main([str(missing), "--skip-reason", "unsupported distro"]) == 0
    assert "deliberately inapplicable" in capsys.readouterr().out


def test_self_disable_without_skip_reason_fails(tmp_path, capsys):
    """Same 0-passing report, but no inapplicability reason: fail closed."""
    path = _write(tmp_path, _report("skipped"))
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "0 passing scenarios" in out
    assert "deliberately inapplicable" not in out


def test_empty_skip_reason_is_treated_as_no_marker(tmp_path, capsys):
    """An empty --skip-reason must not exempt a self-disabled suite."""
    path = _write(tmp_path, _report("skipped"))
    assert main([str(path), "--skip-reason", ""]) == 1
    assert "0 passing scenarios" in capsys.readouterr().out


def test_failed_setup_marker_wins_over_skip_reason(tmp_path, capsys):
    """Fail-closed wins: a setup failure blocks even if a skip reason is given."""
    marker = tmp_path / "results" / "failed_setup.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("qecore-headless startup failed", encoding="utf-8")
    results = _write(tmp_path, _report("skipped"))
    assert main([str(results), "--skip-reason", "reason", "--failed-setup-marker", str(marker)]) == 1
    assert "before_all setup failed" in capsys.readouterr().out



# ---------------------------------------------------------------------------
# --allow-all-skipped: a shard whose only scenarios legitimately all skip
# (smoke-firefox on a Flatpak-only-Firefox image, #924) passes when every
# scenario was skipped, and only then.
# ---------------------------------------------------------------------------


def test_allow_all_skipped_passes_an_all_skipped_run(tmp_path, capsys):
    path = _write(tmp_path, _report("skipped"))
    assert main([str(path), "--allow-all-skipped"]) == 0
    assert "every scenario was skipped" in capsys.readouterr().out


def test_allow_all_skipped_still_fails_a_failed_scenario(tmp_path, capsys):
    path = _write(tmp_path, _report("skipped", "failed"))
    assert main([str(path), "--allow-all-skipped"]) == 1
    assert "0 passing scenarios" in capsys.readouterr().out


def test_allow_all_skipped_still_fails_undefined(tmp_path, capsys):
    path = _write(tmp_path, _report("skipped", "undefined"))
    assert main([str(path), "--allow-all-skipped"]) == 1


def test_allow_all_skipped_still_fails_an_empty_report(tmp_path, capsys):
    path = _write(tmp_path, [])
    assert main([str(path), "--allow-all-skipped"]) == 1


def test_failed_setup_marker_wins_over_allow_all_skipped(tmp_path, capsys):
    marker = tmp_path / "results" / "failed_setup.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("qecore-headless startup failed", encoding="utf-8")
    results = _write(tmp_path, _report("skipped"))
    assert main([str(results), "--allow-all-skipped", "--failed-setup-marker", str(marker)]) == 1
    assert "before_all setup failed" in capsys.readouterr().out

# ---------------------------------------------------------------------------
# Bad / incomplete input
# ---------------------------------------------------------------------------


def test_missing_results_file_exits_one(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.json"
    assert main([str(missing)]) == 1
    assert "No results.json found" in capsys.readouterr().out


def test_failed_setup_marker_exits_one_even_with_passed(tmp_path, capsys):
    """A before_all failure writes the marker and skips every scenario; behave
    exits 0. The gate must fail closed on the marker before trusting results."""
    marker = tmp_path / "results" / "failed_setup.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("qecore-headless startup failed", encoding="utf-8")
    # Even with a fully passing results.json present, the marker wins.
    results = _write(tmp_path, _report("passed", "passed"))
    assert main([str(results), "--failed-setup-marker", str(marker)]) == 1
    out = capsys.readouterr().out
    assert "before_all setup failed" in out
    assert "Traceback" not in out


def test_empty_results_file_exits_one(tmp_path, capsys):
    path = _write_text(tmp_path, "")
    assert main([str(path)]) == 1
    assert "empty" in capsys.readouterr().out


def test_whitespace_only_results_file_exits_one(tmp_path, capsys):
    path = _write_text(tmp_path, "   \n  ")
    assert main([str(path)]) == 1
    assert "empty" in capsys.readouterr().out


def test_malformed_json_exits_one_without_traceback(tmp_path, capsys):
    path = _write_text(tmp_path, "not json at all {{{")
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "incomplete or truncated" in out
    assert "Traceback" not in out


@pytest.mark.parametrize("payload", ['{"features": []}', "42", '"string"'])
def test_non_list_json_exits_one(tmp_path, capsys, payload):
    path = _write_text(tmp_path, payload)
    assert main([str(path)]) == 1
    assert "incomplete or truncated" in capsys.readouterr().out


def test_truncated_final_object_exits_one(tmp_path, capsys):
    """Two whole features plus a cut-off third object: salvage drops the tail."""
    path = _write_text(
        tmp_path,
        '[{"name": "a", "elements": []}, '
        '{"name": "b", "elements": []}, '
        '{"name": "c", "elements": [{"type": '[:60],
    )
    assert main([str(path)]) == 1
    assert "incomplete or truncated" in capsys.readouterr().out


def test_non_dict_feature_entry_exits_one(tmp_path, capsys):
    path = _write(tmp_path, ["oops"])
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "0 passing scenarios" in out
    assert "Traceback" not in out


def test_non_dict_element_entry_exits_one(tmp_path, capsys):
    path = _write(tmp_path, [{"name": "f", "elements": ["oops"]}])
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "0 passing scenarios" in out
    assert "Traceback" not in out


# ---------------------------------------------------------------------------
# Truncated-but-salvageable report still fails: passed count is not trusted
# ---------------------------------------------------------------------------


def test_salvaged_partial_report_counts_are_not_trusted(tmp_path, capsys):
    """Even when salvage recovers features, an incomplete report fails closed."""
    path = _write_text(
        tmp_path,
        '[{"name": "a", "elements": [{"type": "scenario", "name": "x", '
        '"status": "passed"}]}, '
        '{"name": "b", "elements": [{"type": "scenario", "name": "y", '
        '"status": "passed"}]}, '
        '{"name": "c", "elements": [{"type": "scenario", "name": "z", "s'[:60],
    )
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "incomplete or truncated" in out


# ---------------------------------------------------------------------------
# Defaults and CLI
# ---------------------------------------------------------------------------


def test_cli_defaults_to_results_results_json(tmp_path, capsys):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "results.json").write_text(
        json.dumps(_report("passed")), encoding="utf-8"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "passed=1" in completed.stdout


def test_cli_exits_one_on_all_undefined(tmp_path):
    path = _write(tmp_path, _report("undefined"))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "0 passing scenarios" in completed.stdout
    assert "Traceback" not in completed.stderr


def test_cli_defaults_to_missing_results_json_exits_one(tmp_path):
    """No results.json present: the CLI default fails closed like the import path."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "No results.json found" in completed.stdout
