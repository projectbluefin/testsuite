"""Unit tests for dashboard/scripts/convert_behave.py.

convert_behave.py turns a behave ``results.json`` pulled off GHCR into the
dashboard's per-run asset (publish-to-pages.yml, "Extract Run Metadata &
Convert Behave JSON"). Nothing else validates that payload: a scenario the
converter miscounts, a duration it drops, or a step error it fails to surface
is published to the dashboard as fact, and a non-zero exit fails the whole
Pages deploy.

Only run_id sanitization was exercised before (test_dashboard_run_id_
sanitization.py); these tests cover the conversion arithmetic, the status
mapping, the slug split, the log/error assembly, and the CLI wrapper.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "dashboard" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


convert_behave = _load("convert_behave")


def _scenario(name="scenario", status="passed", steps=(), element_type="scenario"):
    return {
        "type": element_type,
        "name": name,
        "status": status,
        "steps": list(steps),
    }


def _step(keyword="Given", name="a step", status="passed", duration=0.0, **result):
    return {
        "keyword": keyword,
        "name": name,
        "result": {"status": status, "duration": duration, **result},
    }


def _feature(name="feature", elements=()):
    return {"name": name, "elements": list(elements)}


def _convert(features, tmp_path, **kwargs):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(features))
    options = {
        "run_id": "run-1",
        "caller_repo": "projectbluefin/utah",
        "slug": "bluefin-testing",
        "suite": "smoke",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    options.update(kwargs)
    return convert_behave.convert_behave_json(str(path), **options)


# --- normalize_status -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("passed", "passed"),
        ("PASSED", "passed"),
        ("  passed  ", "passed"),
        ("failed", "failed"),
        ("error", "failed"),
        ("skipped", "skipped"),
        ("undefined", "failed"),
        ("untested", "failed"),
        ("hook_error", "failed"),
        ("banana", "failed"),
    ],
)
def test_normalize_status_maps_behave_statuses(raw, expected):
    assert convert_behave.normalize_status(raw) == expected


@pytest.mark.parametrize("raw", [None, "", 0])
def test_normalize_status_treats_missing_status_as_failed(raw):
    """A status behave never wrote must not be published as a pass."""
    assert convert_behave.normalize_status(raw) == "failed"


# --- load failure -----------------------------------------------------------


def test_missing_behave_json_returns_none(tmp_path):
    assert (
        convert_behave.convert_behave_json(
            str(tmp_path / "absent.json"),
            run_id="run-1",
            caller_repo="",
            slug="bluefin-testing",
            suite="smoke",
            timestamp="",
        )
        is None
    )


def test_truncated_behave_json_returns_none(tmp_path):
    path = tmp_path / "results.json"
    path.write_text('[{"name": "feature", "elements": [')

    assert (
        convert_behave.convert_behave_json(
            str(path),
            run_id="run-1",
            caller_repo="",
            slug="bluefin-testing",
            suite="smoke",
            timestamp="",
        )
        is None
    )


# --- slug split -------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "flavor", "stream"),
    [
        ("bluefin-testing", "bluefin", "testing"),
        ("bluefin-lts-stable", "bluefin-lts", "stable"),
        ("aurora-dx-testing", "aurora-dx", "testing"),
        ("dakota", "dakota", "testing"),
        ("", "", "testing"),
    ],
)
def test_slug_splits_into_flavor_and_stream(slug, flavor, stream, tmp_path):
    run = _convert([], tmp_path, slug=slug)

    assert (run["flavor"], run["stream"]) == (flavor, stream)


# --- counting and summary ---------------------------------------------------


def test_background_elements_are_not_counted_as_scenarios(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(name="setup", element_type="background"),
                    _scenario(name="real", status="passed"),
                ]
            )
        ],
        tmp_path,
    )

    assert run["summary"]["total_tests"] == 1
    assert [t["name"] for t in run["tests"]] == ["feature > real"]


def test_summary_counts_each_status_bucket(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(name="a", status="passed"),
                    _scenario(name="b", status="failed"),
                    _scenario(name="c", status="error"),
                    _scenario(name="d", status="skipped"),
                ]
            )
        ],
        tmp_path,
    )

    assert run["summary"]["passed_tests"] == 1
    assert run["summary"]["failed_tests"] == 2
    assert run["summary"]["skipped_tests"] == 1
    assert run["summary"]["total_tests"] == 4
    assert run["summary"]["status"] == "failed"


def test_all_passed_run_reports_success(tmp_path):
    run = _convert([_feature(elements=[_scenario(status="passed")])], tmp_path)

    assert run["summary"]["status"] == "success"


def test_empty_report_is_not_reported_as_success(tmp_path):
    """A behave run that produced no scenarios is a broken run, not a green one."""
    run = _convert([], tmp_path)

    assert run["summary"]["total_tests"] == 0
    assert run["summary"]["status"] == "failed"


def test_skipped_scenario_is_published_as_skipped_status(tmp_path):
    """A @pending/@future skip must not render as a red failed row.

    LogViewer.astro draws ``skipped`` grey and collapsed; publishing it as
    ``failed`` put every stub scenario in red under a SUCCESS badge.
    """
    run = _convert([_feature(elements=[_scenario(status="skipped")])], tmp_path)

    assert run["tests"][0]["status"] == "skipped"
    assert run["summary"]["skipped_tests"] == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("passed", "passed"),
        ("failed", "failed"),
        ("error", "failed"),
        ("undefined", "failed"),
        ("hook_error", "failed"),
        (None, "failed"),
    ],
)
def test_per_test_status_matches_the_summary_bucket(tmp_path, raw, expected):
    run = _convert([_feature(elements=[_scenario(status=raw)])], tmp_path)

    assert run["tests"][0]["status"] == expected


def test_step_durations_sum_into_milliseconds(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(
                        name="a",
                        steps=[_step(duration=1.5), _step(duration=0.25)],
                    ),
                    _scenario(name="b", steps=[_step(duration=2.0)]),
                ]
            )
        ],
        tmp_path,
    )

    assert [t["duration_ms"] for t in run["tests"]] == [1750, 2000]
    assert run["summary"]["total_duration_ms"] == 3750


def test_step_without_duration_contributes_zero(tmp_path):
    run = _convert(
        [_feature(elements=[_scenario(steps=[{"keyword": "Given", "name": "s"}])])],
        tmp_path,
    )

    assert run["tests"][0]["duration_ms"] == 0
    assert run["summary"]["total_duration_ms"] == 0


# --- logs and error messages ------------------------------------------------


def test_step_error_message_is_surfaced_on_the_test(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(
                        status="failed",
                        steps=[
                            _step(name="ok"),
                            _step(
                                keyword="Then",
                                name="boom",
                                status="failed",
                                error_message="AssertionError: nope",
                            ),
                        ],
                    )
                ]
            )
        ],
        tmp_path,
    )

    test = run["tests"][0]
    assert test["error_message"] == "AssertionError: nope"
    assert "[ERROR] AssertionError: nope" in test["logs"]
    assert "[PASSED] Given ok" in test["logs"]
    assert "[FAILED] Then boom" in test["logs"]


def test_multi_line_error_message_is_joined_into_text(tmp_path):
    """behave writes a multi-line error (every traceback) as a list of lines."""
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(
                        status="failed",
                        steps=[
                            _step(
                                status="failed",
                                error_message=["Traceback:", "  AssertionError: nope"],
                            )
                        ],
                    )
                ]
            )
        ],
        tmp_path,
    )

    test = run["tests"][0]
    assert test["error_message"] == "Traceback:\n  AssertionError: nope"
    assert "[ERROR] Traceback:\n  AssertionError: nope" in test["logs"]
    assert "['" not in test["logs"]


@pytest.mark.parametrize("raw", [None, "", []])
def test_error_text_treats_empty_messages_as_none(raw):
    assert convert_behave.error_text(raw) is None


def test_last_step_error_message_wins(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(
                        status="failed",
                        steps=[
                            _step(status="failed", error_message="first"),
                            _step(status="failed", error_message="second"),
                        ],
                    )
                ]
            )
        ],
        tmp_path,
    )

    assert run["tests"][0]["error_message"] == "second"


def test_passing_scenario_has_no_error_message(tmp_path):
    run = _convert([_feature(elements=[_scenario(steps=[_step()])])], tmp_path)

    assert run["tests"][0]["error_message"] is None


def test_step_text_and_table_are_appended_to_logs(tmp_path):
    run = _convert(
        [
            _feature(
                elements=[
                    _scenario(
                        name="text",
                        steps=[dict(_step(name="with text"), text="stdout body")],
                    ),
                    _scenario(
                        name="table",
                        steps=[dict(_step(name="with table"), table={"rows": [["a"]]})],
                    ),
                ]
            )
        ],
        tmp_path,
    )

    assert "Output:\nstdout body" in run["tests"][0]["logs"]
    assert "Output:\n" in run["tests"][1]["logs"]


def test_test_name_is_feature_then_scenario(tmp_path):
    run = _convert(
        [_feature(name="Smoke", elements=[_scenario(name="It boots")])], tmp_path
    )

    assert run["tests"][0]["name"] == "Smoke > It boots"


def test_unnamed_feature_and_scenario_fall_back_to_placeholders(tmp_path):
    run = _convert([{"elements": [{"type": "scenario", "status": "passed"}]}], tmp_path)

    assert run["tests"][0]["name"] == "unknown_feature > unknown_scenario"


# --- envelope ---------------------------------------------------------------


def test_envelope_carries_identity_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")

    run = _convert([], tmp_path, run_id="run-42", caller_repo="projectbluefin/utah")

    assert run["id"] == "run-42"
    assert run["timestamp"] == "2026-01-01T00:00:00Z"
    assert run["suite"] == "smoke"
    assert run["git_commit"]["sha"] == "deadbeef"
    assert run["git_commit"]["repo_url"] == "https://github.com/projectbluefin/utah"


def test_missing_caller_repo_falls_back_to_testsuite(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    run = _convert([], tmp_path, caller_repo="")

    assert run["git_commit"]["sha"] == "unknown"
    assert run["git_commit"]["repo_url"] == (
        "https://github.com/projectbluefin/testsuite"
    )


def test_unsafe_run_id_falls_back_to_a_generated_id(tmp_path):
    """publish-to-pages.yml feeds run_id straight from a GHCR annotation."""
    run = _convert([], tmp_path, run_id="../../../pwn", slug="bluefin-testing")

    assert run["id"].startswith("run_")
    assert run["id"].endswith("_bluefin-testing")
    assert ".." not in run["id"]


def test_empty_timestamp_is_generated(tmp_path):
    run = _convert([], tmp_path, timestamp="")

    assert run["timestamp"].endswith("Z")
    assert len(run["timestamp"]) == len("2026-01-01T00:00:00Z")


# --- CLI --------------------------------------------------------------------


def _run_main(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["convert_behave.py", *argv])
    return convert_behave.main()


def test_main_writes_the_run_asset_named_after_the_run_id(tmp_path, monkeypatch):
    behave_json = tmp_path / "results.json"
    behave_json.write_text(
        json.dumps([_feature(elements=[_scenario(steps=[_step(duration=0.5)])])])
    )
    out_dir = tmp_path / "runs" / "nested"

    _run_main(
        [
            str(behave_json),
            "run-7",
            "projectbluefin/utah",
            "bluefin-testing",
            "smoke",
            "2026-01-01T00:00:00Z",
            str(out_dir),
        ],
        monkeypatch,
    )

    written = json.loads((out_dir / "run-7.json").read_text())
    assert written["summary"]["passed_tests"] == 1
    assert written["summary"]["total_duration_ms"] == 500


def test_main_exits_non_zero_when_conversion_fails(tmp_path, monkeypatch):
    """A failed conversion must fail the Pages deploy, not publish nothing."""
    out_dir = tmp_path / "runs"

    with pytest.raises(SystemExit) as excinfo:
        _run_main(
            [
                str(tmp_path / "absent.json"),
                "run-7",
                "",
                "bluefin-testing",
                "smoke",
                "",
                str(out_dir),
            ],
            monkeypatch,
        )

    assert excinfo.value.code == 1
    assert not list(out_dir.glob("*.json"))


def test_main_rejects_a_short_argument_list(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _run_main([str(tmp_path / "results.json"), "run-7"], monkeypatch)

    assert excinfo.value.code == 1
    assert "Usage:" in capsys.readouterr().out
