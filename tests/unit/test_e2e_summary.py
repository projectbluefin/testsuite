"""Unit tests for e2e job-summary result counting."""

import json
from scripts.e2e_summary import (
    count_scenarios,
    is_success,
    load_report,
    scenario_statuses,
    summary_icon,
)


def _report(*statuses, element_type="scenario"):
    return [
        {"elements": [{"type": element_type, "status": s} for s in statuses]}
    ]


def test_count_scenarios_counts_only_scenario_statuses():
    report = [
        {
            "elements": [
                {"type": "background", "status": "passed"},
                {"type": "scenario", "status": "passed"},
                {"type": "scenario", "status": "failed"},
                {"type": "scenario", "status": "skipped"},
                {"type": "scenario", "status": "undefined"},
                {"type": "scenario", "status": "untested"},
            ]
        }
    ]

    assert count_scenarios(report) == {
        "passed": 1,
        "failed": 1,
        "skipped": 1,
        "undefined": 1,
        "untested": 1,
        "other": 0,
    }


def test_count_scenarios_does_not_infer_passed_from_unknown_statuses():
    counts = count_scenarios(_report("undefined", "untested", "error"))

    assert counts["passed"] == 0


def test_behave_error_statuses_are_counted_not_dropped():
    """behave 1.3.3 emits ``error``/``hook_error`` (Scenario.compute_status)."""
    report = _report("passed", "undefined", "untested", "error", "hook_error")

    counts = count_scenarios(report)

    assert counts["other"] == 2
    assert sum(counts.values()) == 5


def test_unknown_status_string_is_bucketed():
    counts = count_scenarios(_report("passed", "banana-status", None))

    assert counts["passed"] == 1
    assert counts["other"] == 2
    assert sum(counts.values()) == 3


def test_missing_status_key_is_bucketed():
    report = [{"elements": [{"type": "scenario"}]}]

    counts = count_scenarios(report)

    assert counts["other"] == 1
    assert sum(counts.values()) == 1


def test_features_without_elements_are_tolerated():
    assert sum(count_scenarios([{}, {"elements": None}]).values()) == 0


def test_success_requires_passed_or_skipped_only():
    assert is_success(count_scenarios(_report("passed", "skipped")))
    assert summary_icon(count_scenarios(_report("passed", "skipped"))) == "✅"


def test_undefined_only_run_is_not_success():
    counts = count_scenarios(_report("undefined"))

    assert counts["failed"] == 0
    assert not is_success(counts)
    assert summary_icon(counts) == "⚠️"


def test_untested_only_run_is_not_success():
    counts = count_scenarios(_report("untested"))

    assert counts["failed"] == 0
    assert not is_success(counts)
    assert summary_icon(counts) == "⚠️"


def test_errored_run_with_zero_failures_is_not_success():
    counts = count_scenarios(_report("passed", "error", "hook_error"))

    assert counts["failed"] == 0
    assert not is_success(counts)
    assert summary_icon(counts) == "⚠️"


def test_failed_run_renders_failure_icon():
    counts = count_scenarios(_report("passed", "failed", "error"))

    assert summary_icon(counts) == "❌"


def test_skipped_only_and_empty_runs_stay_green():
    counts = count_scenarios(_report("skipped"))

    assert summary_icon(counts) == "✅"
    assert summary_icon(count_scenarios([])) == "✅"


def test_scenario_statuses_excludes_backgrounds():
    report = [
        {
            "elements": [
                {"type": "background", "name": "Shared setup", "status": "passed"},
                {"type": "scenario", "name": "launch", "status": "failed"},
                {"type": "scenario", "name": "quit", "status": "passed"},
            ]
        }
    ]

    assert scenario_statuses(report) == {"launch": "failed", "quit": "passed"}


def test_scenario_statuses_skips_nameless_elements():
    report = [{"elements": [{"type": "scenario", "status": "passed"}]}]

    assert scenario_statuses(report) == {}


def test_scenario_statuses_defaults_missing_status_to_unknown():
    report = [{"elements": [{"type": "scenario", "name": "orphan"}]}]

    assert scenario_statuses(report) == {"orphan": "unknown"}


def test_scenario_statuses_tolerates_features_without_elements():
    assert scenario_statuses([{}, {"elements": None}]) == {}


def _feature(name="feature", status="passed"):
    return {"name": name, "elements": [{"type": "scenario", "name": name, "status": status}]}


def test_load_report_parses_valid_json_unchanged():
    report = [_feature("a"), _feature("b")]

    assert load_report(json.dumps(report)) == report


def test_load_report_empty_input_returns_empty_list():
    assert load_report("") == []


def test_load_report_open_bracket_only_returns_empty_list():
    assert load_report("[") == []


def test_load_report_salvages_complete_features_without_footer():
    # behave flushes each completed feature in eof() and writes the closing
    # ']' only in close(); a crash before close() leaves the objects minus the
    # footer. Every complete feature must survive.
    report = [_feature("a"), _feature("b"), _feature("c")]
    crashed = json.dumps(report)[:-1]  # drop the trailing ']'

    assert load_report(crashed) == report
    assert count_scenarios(load_report(crashed))["passed"] == 3


def test_load_report_drops_truncated_final_feature():
    report = [_feature("a"), _feature("b"), _feature("c")]
    truncated = json.dumps(report)[: len(json.dumps(report)) - 5]  # chop part of last

    recovered = load_report(truncated)

    assert [f["name"] for f in recovered] == ["a", "b"]


def test_load_report_trailing_comma_without_object_returns_features():
    report = [_feature("a"), _feature("b")]
    crashed = json.dumps(report) + ","  # complete objects, then a dangling comma

    assert [f["name"] for f in load_report(crashed)] == ["a", "b"]
