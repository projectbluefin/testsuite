from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.check_quarantine_age import (
    FeatureScenario,
    QuarantineEntry,
    RECOMMENDED_ACTION,
    build_quarantine_entries,
    file_history_entries,
    find_expired_quarantines,
    format_json,
    format_report,
    parse_feature_scenarios,
    scenario_quarantine_dates,
    validate_args,
)


def _entry(*, age_days: int, threshold_days: int = 30) -> QuarantineEntry:
    quarantined_on = date(2026, 1, 1)
    return QuarantineEntry(
        feature_file=Path("tests/smoke/features/example.feature"),
        scenario_name="Example scenario",
        quarantined_on=quarantined_on,
        age_days=age_days,
        threshold_days=threshold_days,
    )


def test_scenario_over_30_days_fails():
    expired = find_expired_quarantines([_entry(age_days=31)])

    assert [entry.scenario_name for entry in expired] == ["Example scenario"]


def test_scenario_under_30_days_passes():
    expired = find_expired_quarantines([_entry(age_days=29)])

    assert expired == []


def test_output_format_lists_actionable_details():
    report = format_report([_entry(age_days=45)], max_days=30, grace_days=0)

    assert "ERROR: Found 1 @quarantine scenario(s) older than 30 days" in report
    assert "Feature file: tests/smoke/features/example.feature" in report
    assert "Scenario: Example scenario" in report
    assert "Date quarantined: 2026-01-01" in report
    assert "Age: 45 days" in report
    assert f"Action: {RECOMMENDED_ACTION}" in report


def test_json_output_uses_days_field():
    payload = format_json([_entry(age_days=12)])

    assert '"days": 12' in payload
    assert '"quarantined_on": "2026-01-01"' in payload
    assert '"feature_file": "tests/smoke/features/example.feature"' in payload


# --- parse_feature_scenarios ---

_SAMPLE_FEATURE = """\
@common @bluefin
Feature: Example feature

  Background:
    * Setup step

  @smoke @retry
  Scenario: First scenario
    * Step one

  @quarantine
  Scenario: Quarantined scenario
    * Step two

  Scenario Outline: Outline scenario
    * Step <x>

  Examples:
    | x |
    | 1 |
"""


def test_parse_feature_scenarios_returns_all_scenarios():
    fp = Path("tests/example.feature")
    scenarios = parse_feature_scenarios(_SAMPLE_FEATURE, fp)
    assert [s.name for s in scenarios] == [
        "First scenario",
        "Quarantined scenario",
        "Outline scenario",
    ]


def test_parse_feature_scenarios_inherits_feature_tags():
    fp = Path("tests/example.feature")
    scenarios = parse_feature_scenarios(_SAMPLE_FEATURE, fp)
    # Feature-level tags (@common, @bluefin) are inherited by all scenarios
    assert "common" in scenarios[0].tags
    assert "bluefin" in scenarios[0].tags


def test_parse_feature_scenarios_scenario_tags_included():
    fp = Path("tests/example.feature")
    scenarios = parse_feature_scenarios(_SAMPLE_FEATURE, fp)
    first = next(s for s in scenarios if s.name == "First scenario")
    assert "smoke" in first.tags
    assert "retry" in first.tags


def test_parse_feature_scenarios_quarantine_tag():
    fp = Path("tests/example.feature")
    scenarios = parse_feature_scenarios(_SAMPLE_FEATURE, fp)
    quarantined = next(s for s in scenarios if s.name == "Quarantined scenario")
    assert "quarantine" in quarantined.tags


def test_parse_feature_scenarios_background_not_included():
    fp = Path("tests/example.feature")
    scenarios = parse_feature_scenarios(_SAMPLE_FEATURE, fp)
    names = [s.name for s in scenarios]
    assert "Shared setup" not in names
    assert "Setup step" not in names


def test_parse_feature_scenarios_empty_content():
    assert parse_feature_scenarios("", Path("empty.feature")) == []


def test_parse_feature_scenarios_no_scenarios():
    content = "Feature: Empty\n  Background:\n    * Setup\n"
    assert parse_feature_scenarios(content, Path("f.feature")) == []


# --- file_history_entries ---

# `git log --follow --name-only --format=%x00%H%x09%aI`: newest first, each
# record carrying the path the file had at that commit.
_GIT_LOG_OUTPUT = (
    "\x00def456\t2026-01-20T12:00:00+00:00\n\ntests/smoke/features/f.feature\n"
    "\x00abc123\t2026-01-15T10:00:00+00:00\n\ntests/smoke/features/old.feature\n"
)


def test_file_history_entries_parses_log(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _GIT_LOG_OUTPUT

    with patch("scripts.check_quarantine_age.git", return_value=mock_result):
        entries = file_history_entries(tmp_path, tmp_path / "tests/smoke/features/f.feature")

    assert len(entries) == 2
    sha, dt, path = entries[0]
    assert sha == "abc123"
    assert dt.date() == date(2026, 1, 15)
    assert path == "tests/smoke/features/old.feature"


def test_file_history_entries_raises_on_git_failure(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 128
    mock_result.stderr = "fatal: not a git repository"

    with patch("scripts.check_quarantine_age.git", return_value=mock_result):
        with pytest.raises(RuntimeError, match="fatal: not a git repository"):
            file_history_entries(tmp_path, tmp_path / "tests/f.feature")


def test_file_history_entries_ignores_blank_lines(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "\x00abc123\t2026-01-15T10:00:00+00:00\n\n"

    with patch("scripts.check_quarantine_age.git", return_value=mock_result):
        entries = file_history_entries(tmp_path, tmp_path / "tests/f.feature")

    assert len(entries) == 1


# --- scenario_quarantine_dates ---

_FEATURE_V1 = "Feature: F\n\nScenario: My scenario\n  * Step\n"
_FEATURE_V2 = "Feature: F\n\n@quarantine\nScenario: My scenario\n  * Step\n"


def test_scenario_quarantine_dates_finds_first_quarantine(tmp_path):
    from datetime import datetime, timezone
    history_real = [
        ("sha1", datetime(2026, 1, 10, tzinfo=timezone.utc), "tests/smoke/features/f.feature"),
        ("sha2", datetime(2026, 1, 20, tzinfo=timezone.utc), "tests/smoke/features/f.feature"),
    ]

    def fake_git(*args, repo_root):
        sha = args[1].split(":")[0] if args[0] == "show" else None
        result = MagicMock()
        result.returncode = 0
        if sha == "sha1":
            result.stdout = _FEATURE_V1  # not quarantined yet
        else:
            result.stdout = _FEATURE_V2  # quarantined in sha2
        return result

    feature_file = tmp_path / "tests/smoke/features/f.feature"
    with patch("scripts.check_quarantine_age.file_history_entries", return_value=history_real):
        with patch("scripts.check_quarantine_age.git", side_effect=fake_git):
            dates = scenario_quarantine_dates(tmp_path, feature_file, {"My scenario"})

    assert "My scenario" in dates
    quarantined_on, source = dates["My scenario"]
    assert quarantined_on == date(2026, 1, 20)
    assert source == "history"


# --- build_quarantine_entries ---

def test_build_quarantine_entries_returns_sorted_by_age(tmp_path):

    scenarios = [
        FeatureScenario(
            feature_file=tmp_path / "tests/smoke/features/f.feature",
            name="Old scenario",
            tags=("quarantine",),
            line_number=5,
        ),
        FeatureScenario(
            feature_file=tmp_path / "tests/smoke/features/f.feature",
            name="New scenario",
            tags=("quarantine",),
            line_number=10,
        ),
    ]

    today = date(2026, 6, 1)
    quarantine_dates = {
        "Old scenario": (date(2026, 1, 1), "history"),
        "New scenario": (date(2026, 5, 1), "history"),
    }

    with patch("scripts.check_quarantine_age.scenario_quarantine_dates", return_value=quarantine_dates):
        entries = build_quarantine_entries(
            scenarios, today=today, max_days=30, grace_days=0, repo_root=tmp_path
        )

    assert entries[0].scenario_name == "Old scenario"  # older first
    assert entries[0].age_days == 151
    assert entries[1].scenario_name == "New scenario"
    assert entries[1].age_days == 31


# --- validate_args ---

def test_validate_args_rejects_negative_max_days():
    args = MagicMock()
    args.max_days = -1
    args.grace_days = 0
    with pytest.raises(ValueError, match="--max-days"):
        validate_args(args)


def test_validate_args_rejects_negative_grace_days():
    args = MagicMock()
    args.max_days = 30
    args.grace_days = -1
    with pytest.raises(ValueError, match="--grace-days"):
        validate_args(args)


def test_validate_args_accepts_zero():
    args = MagicMock()
    args.max_days = 0
    args.grace_days = 0
    validate_args(args)  # should not raise


# --- format_report: no-expired case ---

def test_format_report_ok_when_no_expired():
    report = format_report([], max_days=30, grace_days=0)
    assert report.startswith("OK:")
    assert "30 days" in report


def test_format_report_includes_grace_in_threshold():
    report = format_report([], max_days=30, grace_days=5)
    assert "35 days" in report


# --- main() exit code ---

def test_main_exits_zero_when_no_expired(tmp_path):
    """main() returns 0 when all quarantined scenarios are within threshold."""
    import scripts.check_quarantine_age as mod

    with patch.object(mod, "find_quarantined_scenarios", return_value=[]):
        with patch.object(mod, "build_quarantine_entries", return_value=[]):
            with patch("sys.argv", ["check_quarantine_age.py", "--repo-root", str(tmp_path)]):
                rc = mod.main()
    assert rc == 0


def test_main_exits_one_when_expired(tmp_path):
    """main() returns 1 when at least one scenario is expired."""
    import scripts.check_quarantine_age as mod

    expired_entry = _entry(age_days=60)

    with patch.object(mod, "find_quarantined_scenarios", return_value=[]):
        with patch.object(mod, "build_quarantine_entries", return_value=[expired_entry]):
            with patch("sys.argv", ["check_quarantine_age.py", "--repo-root", str(tmp_path)]):
                rc = mod.main()
    assert rc == 1


def test_main_json_flag_exits_zero(tmp_path):
    """--json always exits 0 and prints JSON."""
    import scripts.check_quarantine_age as mod

    expired_entry = _entry(age_days=60)

    with patch.object(mod, "find_quarantined_scenarios", return_value=[]):
        with patch.object(mod, "build_quarantine_entries", return_value=[expired_entry]):
            with patch("sys.argv", ["check_quarantine_age.py", "--repo-root", str(tmp_path), "--json"]):
                rc = mod.main()
    assert rc == 0
