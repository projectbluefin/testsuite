"""Unit tests for scripts/quarantine_citations.py (the PR validation check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quarantine_citations import (
    Citation,
    format_report,
    main,
    parse_citation,
    parse_feature,
    scan,
)

FEATURE = Path("tests/smoke/features/example.feature")
CITE = "# quarantine: projectbluefin/dakota#1875 extension missing on dakota:testing"


def _parse(text: str):
    return parse_feature(text, FEATURE)


@pytest.mark.parametrize(
    "line, expected",
    [
        (CITE, Citation("projectbluefin/dakota", 1875, "extension missing on dakota:testing")),
        (
            "  # quarantine: projectbluefin/testsuite#7 flaky   ",
            Citation("projectbluefin/testsuite", 7, "flaky"),
        ),
        (
            "#quarantine: projectbluefin/bluefin-bling#12 timing",
            Citation("projectbluefin/bluefin-bling", 12, "timing"),
        ),
    ],
)
def test_good_citations_parse(line, expected):
    assert parse_citation(line) == expected
    assert expected.ref == f"{expected.repo}#{expected.number}"


@pytest.mark.parametrize(
    "line",
    [
        "# quarantine: projectbluefin/dakota#1875",  # no reason
        "# quarantine: dakota#1875 missing",  # no owner
        "# quarantine: ublue-os/bluefin#12 not our org",
        "# quarantine: projectbluefin/dakota #1875 space",
        "# quarantine: projectbluefin/dakota#0 zero",
        "# quarantine: projectbluefin/dakota#18a bad number",
        "# quarantine: https://github.com/projectbluefin/dakota/issues/1875 url",
        "# quarantine: #1143 bare number",
        "# Quarantine: projectbluefin/dakota#1875 wrong case",
        "# Tracking: projectbluefin/testsuite#1143 old free text",
    ],
)
def test_bad_citations_do_not_parse(line):
    assert parse_citation(line) is None


def test_scenario_quarantine_with_citation_is_valid():
    blocks, problems = _parse(
        f"""Feature: Example

  {CITE}
  @smoke @quarantine
  Scenario: One
    * a step

  Scenario: Two
    * a step
"""
    )
    assert problems == []
    assert len(blocks) == 1
    block = blocks[0]
    assert block.level == "scenario"
    assert block.scenarios == ["One"]
    assert block.tag_line == 4
    assert block.citation == parse_citation(CITE)


def test_citation_may_sit_among_other_comments_and_tag_lines():
    blocks, problems = _parse(
        f"""Feature: Example

  # Context about the scenario.
  {CITE}
  @smoke
  @quarantine
  Scenario: One
    * a step
"""
    )
    assert problems == []
    assert blocks[0].tag_line == 6


def test_feature_level_quarantine_covers_every_scenario():
    blocks, problems = _parse(
        f"""{CITE}
@smoke_suite @quarantine
Feature: Example

  Scenario: One
    * a step

  Scenario Outline: Two <n>
    * a step
    Examples:
      | n |
      | 1 |
"""
    )
    assert problems == []
    assert len(blocks) == 1
    assert blocks[0].level == "feature"
    assert blocks[0].name == "Example"
    assert blocks[0].scenarios == ["One", "Two <n>"]


def test_feature_level_quarantine_without_citation_fails():
    _, problems = _parse(
        """@smoke_suite @quarantine
Feature: Example

  Scenario: One
    * a step
"""
    )
    assert len(problems) == 1
    assert problems[0].line == 1
    assert "Feature 'Example' has no citation" in problems[0].message


def test_scenario_under_cited_feature_needs_its_own_citation():
    blocks, problems = _parse(
        f"""{CITE}
@quarantine
Feature: Example

  @quarantine
  Scenario: One
    * a step
"""
    )
    assert len(blocks) == 2
    assert [p.line for p in problems] == [5]


def test_old_free_text_comment_is_not_a_citation():
    _, problems = _parse(
        """Feature: Example

  # Quarantined: dakota:testing omits the extension.
  # Tracking: projectbluefin/testsuite#1143 (Dakota issue could not be filed by hive).
  @extensions @quarantine
  Scenario: One
    * a step
"""
    )
    assert len(problems) == 1
    assert "has no citation" in problems[0].message


def test_citation_separated_by_blank_line_does_not_count():
    _, problems = _parse(
        f"""Feature: Example

  {CITE}

  @quarantine
  Scenario: One
    * a step
"""
    )
    messages = [p.message for p in problems]
    assert any("has no citation" in m for m in messages)
    assert any("no @quarantine tag directly below it" in m for m in messages)


def test_malformed_citation_is_reported_on_its_own_line():
    _, problems = _parse(
        """Feature: Example

  # quarantine: projectbluefin/dakota 1875 missing
  @quarantine
  Scenario: One
    * a step
"""
    )
    assert [p.line for p in problems] == [3]
    assert "malformed quarantine citation" in problems[0].message


def test_two_citations_on_one_quarantine_fail():
    _, problems = _parse(
        f"""Feature: Example

  {CITE}
  # quarantine: projectbluefin/utah#5 also broken on utah
  @quarantine
  Scenario: One
    * a step
"""
    )
    assert len(problems) == 1
    assert "cite exactly one cause" in problems[0].message


def test_stale_citation_after_lift_fails():
    _, problems = _parse(
        f"""Feature: Example

  {CITE}
  @smoke
  Scenario: One
    * a step
"""
    )
    assert [p.line for p in problems] == [3]
    assert "no @quarantine tag directly below it" in problems[0].message


def test_blank_line_between_tags_and_scenario_is_reported():
    _, problems = _parse(
        f"""Feature: Example

  {CITE}
  @quarantine

  Scenario: One
    * a step
"""
    )
    assert any("separated from its keyword by a blank line" in p.message for p in problems)


def test_examples_level_quarantine_needs_citation():
    blocks, problems = _parse(
        f"""Feature: Example

  Scenario Outline: Row <n>
    * a step

    {CITE}
    @quarantine
    Examples:
      | n |
      | 1 |
"""
    )
    assert problems == []
    assert blocks[0].level == "examples"
    assert blocks[0].scenarios == ["Row <n>"]


def test_feature_without_quarantine_is_clean():
    blocks, problems = _parse(
        """@smoke_suite
Feature: Example
  # A description comment.

  @smoke
  Scenario: One
    * a step
"""
    )
    assert blocks == [] and problems == []


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_check_fails_and_reports_file_and_line(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    _write(
        tmp_path,
        "tests/smoke/features/a.feature",
        "Feature: A\n\n  @quarantine\n  Scenario: One\n    * a step\n",
    )
    assert main(["--repo-root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "ERROR: 1 quarantine citation problem(s)" in out
    assert "tests/smoke/features/a.feature:3:" in out
    assert "::error" not in out


def test_check_emits_annotations_under_actions(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _write(
        tmp_path,
        "tests/smoke/features/a.feature",
        "Feature: A\n\n  @quarantine\n  Scenario: One\n    * a step\n",
    )
    assert main(["--repo-root", str(tmp_path)]) == 1
    assert "::error file=tests/smoke/features/a.feature,line=3::" in capsys.readouterr().out


def test_check_passes_with_citations(tmp_path, capsys):
    _write(
        tmp_path,
        "tests/smoke/features/a.feature",
        f"Feature: A\n\n  {CITE}\n  @quarantine\n  Scenario: One\n    * a step\n",
    )
    assert main(["--repo-root", str(tmp_path)]) == 0
    assert "OK: 1 @quarantine tag(s)" in capsys.readouterr().out


def test_check_passes_with_no_quarantines(tmp_path):
    _write(tmp_path, "tests/smoke/features/a.feature", "Feature: A\n\n  Scenario: One\n")
    assert main(["--repo-root", str(tmp_path)]) == 0
    assert format_report([], []).startswith("OK: 0")


def test_repository_feature_files_pass():
    root = Path(__file__).resolve().parents[2]
    _, problems = scan(root)
    assert problems == [], "\n".join(p.format() for p in problems)
