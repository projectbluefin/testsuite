"""Unit tests for shared timing helpers."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.shared import timing


def _context(results_dir, start=None):
    context = SimpleNamespace(
        config=SimpleNamespace(userdata={"results_dir": str(results_dir)}),
    )
    if start is not None:
        context._timing_start = start
    return context


def _scenario(name="Launch app", status="passed", feature="Smoke", tags=None):
    tags = tags or []
    return SimpleNamespace(
        name=name,
        status=SimpleNamespace(name=status),
        feature=SimpleNamespace(name=feature),
        tags=tags,
        effective_tags=tags,
    )


def test_record_start_sets_monotonic_float():
    context = SimpleNamespace()

    with patch("tests.shared.timing.time.monotonic", return_value=12.5):
        timing.record_start(context)

    assert isinstance(context._timing_start, float)
    assert context._timing_start == pytest.approx(12.5)


def test_record_end_writes_jsonl_without_sla_when_no_tag_present(tmp_path):
    context = _context(tmp_path, start=100.0)
    scenario = _scenario()

    with patch("tests.shared.timing.time.monotonic", return_value=102.5):
        elapsed = timing.record_end(context, scenario)

    assert elapsed == pytest.approx(2.5)

    timings_file = tmp_path / "timings.jsonl"
    lines = timings_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert {"scenario", "elapsed", "sla_violated"} <= entry.keys()
    assert entry["scenario"] == scenario.name
    assert entry["elapsed"] == pytest.approx(round(elapsed, 3))
    assert entry["elapsed_s"] == pytest.approx(round(elapsed, 3))
    assert entry["sla_s"] is None
    assert entry["sla_violated"] is False
    assert entry["feature"] == scenario.feature.name
    assert entry["status"] == scenario.status.name


@pytest.mark.parametrize(
    ("tags", "end_time", "expected_sla", "expected_violation"),
    [
        (["sla_3s"], 102.5, 3, False),
        (["smoke", "sla_3s"], 104.25, 3, True),
        (["@sla_15s"], 110.0, 15, False),
    ],
)
def test_record_end_parses_sla_tag_and_sets_sla_status(
    tmp_path,
    tags,
    end_time,
    expected_sla,
    expected_violation,
):
    context = _context(tmp_path, start=100.0)
    scenario = _scenario(tags=tags)

    with patch("tests.shared.timing.time.monotonic", return_value=end_time):
        timing.record_end(context, scenario)

    entry = json.loads((tmp_path / "timings.jsonl").read_text(encoding="utf-8").strip())
    assert entry["sla_s"] == expected_sla
    assert entry["sla_violated"] is expected_violation


def test_record_end_without_start_returns_none(tmp_path):
    context = _context(tmp_path)

    assert timing.record_end(context, _scenario()) is None
    assert not (tmp_path / "timings.jsonl").exists()
