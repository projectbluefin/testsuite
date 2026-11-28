"""Unit tests for scripts/update_coverage_snapshot.py.

This script is a required PR gate (``.github/workflows/pr-validate.yml`` runs
``python3 scripts/update_coverage_snapshot.py --check``), so a regression in
its tag parsing or classification silently changes the suite-map numbers that
every test PR is measured against.

Covers: ``parse_scenarios``, ``classify``, ``SuiteCounts.total``,
``count_scenarios``, ``render_snapshot``, ``block_bounds``, ``update_file``
(including ``--check --base-file``) and ``main``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import update_coverage_snapshot as ucs  # noqa: E402


def write_feature(root: Path, relpath: str, content: str) -> Path:
    """Create tests/<relpath> under ``root`` with ``content``."""
    path = root / "tests" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_suite_map(root: Path, body: str) -> Path:
    """Create the suite-map SKILL.md with ``body`` between the markers."""
    path = root / ucs.SUITE_MAP
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Suite map\n\nintro\n\n{body}\n\ntrailer\n",
        encoding="utf-8",
    )
    return path


# ── parse_scenarios ───────────────────────────────────────────────────────────


class TestParseScenarios:
    def test_untagged_scenario_has_empty_tag_set(self):
        content = "Feature: F\n\n  Scenario: one\n    Given a thing\n"
        assert ucs.parse_scenarios(content) == [set()]

    def test_scenario_tags_are_collected(self):
        content = "Feature: F\n\n  @pending @slow\n  Scenario: one\n    Given x\n"
        assert ucs.parse_scenarios(content) == [{"pending", "slow"}]

    def test_feature_tags_are_inherited_by_every_scenario(self):
        content = (
            "@quarantine\n"
            "Feature: F\n"
            "  Scenario: one\n"
            "  Scenario: two\n"
        )
        assert ucs.parse_scenarios(content) == [{"quarantine"}, {"quarantine"}]

    def test_scenario_tags_union_with_feature_tags(self):
        content = "@nvidia\nFeature: F\n  @future\n  Scenario: one\n"
        assert ucs.parse_scenarios(content) == [{"nvidia", "future"}]

    def test_scenario_tags_do_not_leak_to_the_next_scenario(self):
        content = "Feature: F\n  @pending\n  Scenario: one\n  Scenario: two\n"
        assert ucs.parse_scenarios(content) == [{"pending"}, set()]

    def test_scenario_outline_is_counted_once(self):
        content = (
            "Feature: F\n"
            "  @future\n"
            "  Scenario Outline: templated\n"
            "    Given <thing>\n"
            "    Examples:\n"
            "      | thing |\n"
            "      | a     |\n"
            "      | b     |\n"
        )
        assert ucs.parse_scenarios(content) == [{"future"}]

    def test_comments_and_blank_lines_are_ignored(self):
        content = (
            "# @quarantine this is a comment, not a tag\n"
            "\n"
            "Feature: F\n"
            "\n"
            "  Scenario: one\n"
        )
        assert ucs.parse_scenarios(content) == [set()]

    def test_tags_before_rule_or_background_are_discarded(self):
        content = (
            "Feature: F\n"
            "  @stray\n"
            "  Background:\n"
            "    Given setup\n"
            "  Scenario: one\n"
        )
        assert ucs.parse_scenarios(content) == [set()]

    def test_hyphenated_and_underscored_tags_parse(self):
        content = "Feature: F\n  @hardware_blocked @kde-smoke\n  Scenario: one\n"
        assert ucs.parse_scenarios(content) == [{"hardware_blocked", "kde-smoke"}]

    def test_file_without_scenarios_returns_empty_list(self):
        assert ucs.parse_scenarios("Feature: empty\n") == []


# ── classify ──────────────────────────────────────────────────────────────────


class TestClassify:
    def test_no_tags_is_active(self):
        assert ucs.classify(set()) == "active"

    def test_unknown_tags_are_active(self):
        assert ucs.classify({"smoke", "dakota_only"}) == "active"

    @pytest.mark.parametrize("tag", ["hardware_blocked", "future", "pending"])
    def test_backlog_tags_are_pending(self, tag):
        assert ucs.classify({tag}) == "pending"

    def test_quarantine_is_quarantined(self):
        assert ucs.classify({"quarantine"}) == "quarantined"

    @pytest.mark.parametrize("other", ["hardware_blocked", "future", "pending"])
    def test_quarantine_outranks_every_backlog_tag(self, other):
        assert ucs.classify({"quarantine", other}) == "quarantined"


# ── SuiteCounts ───────────────────────────────────────────────────────────────


class TestSuiteCounts:
    def test_total_sums_all_three_buckets(self):
        c = ucs.SuiteCounts(name="smoke", active=3, quarantined=2, pending=5)
        assert c.total == 10

    def test_defaults_are_zero(self):
        c = ucs.SuiteCounts(name="smoke")
        assert (c.active, c.quarantined, c.pending, c.total) == (0, 0, 0, 0)


# ── count_scenarios ───────────────────────────────────────────────────────────


class TestCountScenarios:
    def test_suite_name_is_the_first_path_part_under_tests(self, tmp_path):
        write_feature(
            tmp_path,
            "smoke/features/desktop/gnome.feature",
            "Feature: F\n  Scenario: one\n",
        )
        suites = ucs.count_scenarios(tmp_path)
        assert list(suites) == ["smoke"]
        assert suites["smoke"].active == 1

    def test_counts_are_bucketed_by_tag_precedence(self, tmp_path):
        write_feature(
            tmp_path,
            "common/features/a.feature",
            "Feature: F\n"
            "  Scenario: active one\n"
            "  @pending\n"
            "  Scenario: pending one\n"
            "  @future\n"
            "  Scenario: future one\n"
            "  @hardware_blocked\n"
            "  Scenario: blocked one\n"
            "  @quarantine @pending\n"
            "  Scenario: quarantined one\n",
        )
        c = ucs.count_scenarios(tmp_path)["common"]
        assert (c.active, c.pending, c.quarantined, c.total) == (1, 3, 1, 5)

    def test_multiple_files_in_a_suite_accumulate(self, tmp_path):
        write_feature(tmp_path, "dx/a.feature", "Feature: A\n  Scenario: one\n")
        write_feature(tmp_path, "dx/b.feature", "Feature: B\n  Scenario: two\n")
        assert ucs.count_scenarios(tmp_path)["dx"].active == 2

    def test_multiple_suites_are_kept_separate(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        write_feature(
            tmp_path,
            "nvidia/b.feature",
            "@future\nFeature: B\n  Scenario: two\n",
        )
        suites = ucs.count_scenarios(tmp_path)
        assert sorted(suites) == ["nvidia", "smoke"]
        assert suites["smoke"].active == 1
        assert suites["nvidia"].pending == 1

    def test_non_feature_files_are_ignored(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        write_feature(tmp_path, "smoke/notes.md", "Scenario: not a feature file\n")
        assert ucs.count_scenarios(tmp_path)["smoke"].total == 1


# ── render_snapshot ───────────────────────────────────────────────────────────


class TestRenderSnapshot:
    def test_snapshot_is_wrapped_in_the_markers(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        out = ucs.render_snapshot(tmp_path)
        assert out.startswith(ucs.MARKER_START)
        assert out.endswith(ucs.MARKER_END)

    def test_totals_line_reports_scenarios_and_feature_file_count(self, tmp_path):
        write_feature(
            tmp_path,
            "smoke/a.feature",
            "Feature: A\n  Scenario: one\n  @quarantine\n  Scenario: two\n",
        )
        write_feature(
            tmp_path,
            "dx/b.feature",
            "Feature: B\n  @pending\n  Scenario: three\n",
        )
        out = ucs.render_snapshot(tmp_path)
        assert "3 scenarios across 2 feature files" in out
        assert "1 active, 1 quarantined, 1 " in out

    def test_rows_are_sorted_by_suite_name(self, tmp_path):
        for suite in ("smoke", "common", "dx"):
            write_feature(
                tmp_path, f"{suite}/a.feature", "Feature: A\n  Scenario: one\n"
            )
        rows = [
            line.split("|")[1].strip()
            for line in ucs.render_snapshot(tmp_path).splitlines()
            if line.startswith("| ") and not line.startswith("| Suite")
        ]
        assert rows == ["common", "dx", "smoke"]

    def test_row_columns_match_the_counts(self, tmp_path):
        write_feature(
            tmp_path,
            "smoke/a.feature",
            "Feature: A\n"
            "  Scenario: one\n"
            "  Scenario: two\n"
            "  @quarantine\n"
            "  Scenario: three\n"
            "  @future\n"
            "  Scenario: four\n",
        )
        row = next(
            line
            for line in ucs.render_snapshot(tmp_path).splitlines()
            if line.startswith("| smoke |")
        )
        cells = [c.strip() for c in row.split("|")[1:-1]]
        assert cells[:5] == ["smoke", "4", "2", "1", "1"]

    def test_known_suite_gets_its_hand_maintained_note(self, tmp_path):
        write_feature(tmp_path, "hardware/a.feature", "Feature: A\n  Scenario: one\n")
        row = next(
            line
            for line in ucs.render_snapshot(tmp_path).splitlines()
            if line.startswith("| hardware |")
        )
        assert ucs.SUITE_NOTES["hardware"] in row

    def test_unknown_suite_gets_an_empty_note(self, tmp_path):
        write_feature(tmp_path, "brandnew/a.feature", "Feature: A\n  Scenario: one\n")
        row = next(
            line
            for line in ucs.render_snapshot(tmp_path).splitlines()
            if line.startswith("| brandnew |")
        )
        assert [c.strip() for c in row.split("|")[1:-1]] == [
            "brandnew",
            "1",
            "1",
            "0",
            "0",
            "",
        ]

    def test_header_row_is_present(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        out = ucs.render_snapshot(tmp_path)
        assert (
            "| Suite | Scenarios | Active | Quarantined | Pending/Future | Notes |"
            in out
        )


# ── update_file ───────────────────────────────────────────────────────────────


class TestUpdateFile:
    def test_missing_markers_returns_2_and_explains(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = tmp_path / ucs.SUITE_MAP
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Suite map\n\nno markers here\n", encoding="utf-8")

        assert ucs.update_file(tmp_path, check=False) == 2
        err = capsys.readouterr().err
        assert "markers not found" in err
        assert ucs.MARKER_START in err

    def test_missing_end_marker_returns_2(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, ucs.MARKER_START + "\nstale\n")
        assert ucs.update_file(tmp_path, check=False) == 2

    def test_write_mode_replaces_the_block_and_returns_0(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale table\n{ucs.MARKER_END}"
        )

        assert ucs.update_file(tmp_path, check=False) == 0
        text = path.read_text(encoding="utf-8")
        assert "stale table" not in text
        assert "| smoke | 1 | 1 | 0 | 0 |" in text
        assert "Updated" in capsys.readouterr().out

    def test_write_mode_preserves_content_outside_the_markers(self, tmp_path):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        )
        ucs.update_file(tmp_path, check=False)
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Suite map\n\nintro\n")
        assert text.endswith("trailer\n")

    def test_write_mode_is_idempotent(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        )
        ucs.update_file(tmp_path, check=False)
        first = path.read_text(encoding="utf-8")
        capsys.readouterr()

        assert ucs.update_file(tmp_path, check=False) == 0
        assert path.read_text(encoding="utf-8") == first
        assert "No change" in capsys.readouterr().out

    def test_check_mode_reports_stale_and_returns_1(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        )
        before = path.read_text(encoding="utf-8")

        assert ucs.update_file(tmp_path, check=True) == 1
        assert "STALE" in capsys.readouterr().out
        assert path.read_text(encoding="utf-8") == before, "check must not write"

    def test_check_mode_returns_0_when_current(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")
        ucs.update_file(tmp_path, check=False)
        capsys.readouterr()

        assert ucs.update_file(tmp_path, check=True) == 0
        assert "OK" in capsys.readouterr().out

    def test_check_mode_detects_a_newly_added_scenario(self, tmp_path):
        feature = write_feature(
            tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n"
        )
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")
        ucs.update_file(tmp_path, check=False)
        assert ucs.update_file(tmp_path, check=True) == 0

        feature.write_text(
            "Feature: A\n  Scenario: one\n  Scenario: two\n", encoding="utf-8"
        )
        assert ucs.update_file(tmp_path, check=True) == 1


# ── update_file --check --base-file ───────────────────────────────────────────


def write_base(root: Path, body: str) -> Path:
    """Write a base-branch copy of the suite map, outside the repo tree."""
    path = root / "base-suite-map.md"
    path.write_text(f"# Suite map\n\nbase intro\n\n{body}\n", encoding="utf-8")
    return path


class TestBaseFile:
    def test_block_bounds_cover_both_markers(self):
        text = f"a\n{ucs.MARKER_START}\nx\n{ucs.MARKER_END}\nb\n"
        start, end = ucs.block_bounds(text)
        assert text[start:end] == f"{ucs.MARKER_START}\nx\n{ucs.MARKER_END}"

    def test_block_bounds_is_none_without_markers(self):
        assert ucs.block_bounds("no markers") is None

    def test_untouched_stale_block_passes(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        block = f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        make_suite_map(tmp_path, block)
        base = write_base(tmp_path, block)

        assert ucs.update_file(tmp_path, check=True) == 1, "block really is stale"
        capsys.readouterr()
        assert ucs.update_file(tmp_path, check=True, base_file=base) == 0
        assert "not changed by this pull request" in capsys.readouterr().out

    def test_changed_block_that_matches_the_generator_passes(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")
        base = write_base(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")
        ucs.update_file(tmp_path, check=False)
        capsys.readouterr()

        assert ucs.update_file(tmp_path, check=True, base_file=base) == 0
        assert "up to date" in capsys.readouterr().out

    def test_changed_block_that_is_wrong_fails(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nhand edit\n{ucs.MARKER_END}")
        base = write_base(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")

        assert ucs.update_file(tmp_path, check=True, base_file=base) == 1
        assert "STALE" in capsys.readouterr().out

    def test_missing_base_file_is_an_error(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")

        missing = tmp_path / "nope.md"
        assert ucs.update_file(tmp_path, check=True, base_file=missing) == 2
        assert "does not exist" in capsys.readouterr().err

    def test_base_file_without_markers_is_an_error(self, tmp_path, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        make_suite_map(tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}")
        base = write_base(tmp_path, "no markers here")

        assert ucs.update_file(tmp_path, check=True, base_file=base) == 2
        assert "markers not found in --base-file" in capsys.readouterr().err

    def test_base_file_is_passed_through_from_the_command_line(
        self, tmp_path, monkeypatch
    ):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        block = f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        make_suite_map(tmp_path, block)
        base = write_base(tmp_path, block)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "update_coverage_snapshot.py",
                "--check",
                "--base-file",
                str(base),
                "--repo-root",
                str(tmp_path),
            ],
        )

        assert ucs.main() == 0

    def test_base_file_without_check_is_rejected(self, tmp_path, monkeypatch, capsys):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        block = f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        path = make_suite_map(tmp_path, block)
        base = write_base(tmp_path, block)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "update_coverage_snapshot.py",
                "--base-file",
                str(base),
                "--repo-root",
                str(tmp_path),
            ],
        )

        with pytest.raises(SystemExit) as exc:
            ucs.main()
        assert exc.value.code == 2
        assert "only valid with --check" in capsys.readouterr().err
        assert "stale" in path.read_text(encoding="utf-8"), "must not write"


# ── main ──────────────────────────────────────────────────────────────────────


class TestMain:
    def test_repo_root_argument_is_honoured(self, tmp_path, monkeypatch):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        )
        monkeypatch.setattr(
            sys, "argv", ["update_coverage_snapshot.py", "--repo-root", str(tmp_path)]
        )

        assert ucs.main() == 0
        assert "| smoke | 1 | 1 | 0 | 0 |" in path.read_text(encoding="utf-8")

    def test_check_flag_propagates_and_does_not_write(self, tmp_path, monkeypatch):
        write_feature(tmp_path, "smoke/a.feature", "Feature: A\n  Scenario: one\n")
        path = make_suite_map(
            tmp_path, f"{ucs.MARKER_START}\nstale\n{ucs.MARKER_END}"
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "update_coverage_snapshot.py",
                "--check",
                "--repo-root",
                str(tmp_path),
            ],
        )

        assert ucs.main() == 1
        assert "stale" in path.read_text(encoding="utf-8")


# ── repository invariant ──────────────────────────────────────────────────────


class TestRepositoryInvariant:
    def test_committed_suite_map_has_the_markers(self):
        """The committed block may lag the feature files between refresh PRs,
        so only its markers are a repo invariant; freshness is checked by
        ``Coverage snapshot fresh`` in pr-validate.yml."""
        repo_root = Path(__file__).resolve().parents[2]
        text = (repo_root / ucs.SUITE_MAP).read_text(encoding="utf-8")
        assert ucs.block_bounds(text) is not None
