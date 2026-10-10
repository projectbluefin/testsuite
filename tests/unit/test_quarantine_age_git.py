"""Run scripts/check_quarantine_age.py against a real git repository.

test_quarantine_age.py replaces ``git`` with mocks. That leaves the paths that
read actual history unexercised: feature discovery, ``git log --follow``/``git
show`` across commits, the fallback date for a quarantine that is not committed
yet, and the error raised when a file has no history. The tests below build a
small repository with backdated commits and check the dates the gate derives.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts import check_quarantine_age as qa

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")

FEATURE_PATH = "tests/smoke/features/example.feature"

PLAIN = """Feature: Example

  Scenario: Flaky thing
    Given something

  Scenario: Stable thing
    Given something else
"""

QUARANTINED = """Feature: Example

  @quarantine
  Scenario: Flaky thing
    Given something

  Scenario: Stable thing
    Given something else
"""

QUARANTINED_EDITED = QUARANTINED + """
  Scenario: Added later
    Given a third thing
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    # Keep the host's git configuration and templates out of the repository.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    _git(root, "init", "-q", "--template=", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def _git(root: Path, *args: str, when: str | None = None) -> None:
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when}T12:00:00+00:00"
    subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)


def _commit(root: Path, path: str, content: str, when: str, message: str = "change") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message, when=when)


def test_find_quarantined_scenarios_walks_every_feature_file(repo):
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-01-01")
    _commit(
        repo,
        "tests/kde-smoke/features/nested/other.feature",
        "@quarantine\nFeature: All quarantined\n\n  Scenario: Inherits the tag\n    Given x\n",
        "2026-01-02",
    )
    _commit(repo, "tests/common/features/clean.feature", PLAIN, "2026-01-03")
    # Files outside tests/ and without the .feature suffix are not scanned.
    _commit(repo, "docs/example.feature", QUARANTINED, "2026-01-04")
    _commit(repo, "tests/smoke/features/notes.txt", QUARANTINED, "2026-01-04")

    found = qa.find_quarantined_scenarios(repo)

    assert [(s.feature_file.relative_to(repo).as_posix(), s.name) for s in found] == [
        ("tests/kde-smoke/features/nested/other.feature", "Inherits the tag"),
        ("tests/smoke/features/example.feature", "Flaky thing"),
    ]


def test_find_quarantined_scenarios_without_tests_dir_is_empty(repo):
    assert qa.find_quarantined_scenarios(repo) == []


def test_quarantine_date_is_the_commit_that_added_the_tag(repo):
    _commit(repo, FEATURE_PATH, PLAIN, "2026-01-01")
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-02-01")
    # A later unrelated edit to the same file must not reset the clock.
    _commit(repo, FEATURE_PATH, QUARANTINED_EDITED, "2026-03-01")

    dates = qa.scenario_quarantine_dates(repo, repo / FEATURE_PATH, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 2, 1), "history")}


def test_requarantine_keeps_the_first_quarantine_date(repo):
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-01-01")
    _commit(repo, FEATURE_PATH, PLAIN, "2026-02-01")
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-03-01")

    dates = qa.scenario_quarantine_dates(repo, repo / FEATURE_PATH, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 1, 1), "history")}


def test_uncommitted_quarantine_falls_back_to_file_last_modified(repo):
    _commit(repo, FEATURE_PATH, PLAIN, "2026-01-01")
    _commit(repo, FEATURE_PATH, PLAIN + "\n", "2026-02-15")
    (repo / FEATURE_PATH).write_text(QUARANTINED, encoding="utf-8")

    dates = qa.scenario_quarantine_dates(repo, repo / FEATURE_PATH, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 2, 15), "fallback:file-last-modified")}


def test_mixed_history_and_fallback_in_one_file(repo):
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-01-10")
    (repo / FEATURE_PATH).write_text(
        QUARANTINED.replace("  Scenario: Stable thing", "  @quarantine\n  Scenario: Stable thing"),
        encoding="utf-8",
    )

    dates = qa.scenario_quarantine_dates(
        repo, repo / FEATURE_PATH, {"Flaky thing", "Stable thing"}
    )

    assert dates == {
        "Flaky thing": (date(2026, 1, 10), "history"),
        "Stable thing": (date(2026, 1, 10), "fallback:file-last-modified"),
    }


def test_rename_preserves_the_original_quarantine_date(repo):
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-01-01")
    renamed = "tests/smoke/features/renamed.feature"
    _git(repo, "mv", FEATURE_PATH, renamed)
    _git(repo, "commit", "-q", "-m", "rename", when="2026-04-01")

    dates = qa.scenario_quarantine_dates(repo, repo / renamed, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 1, 1), "history")}


def test_rename_from_non_ascii_path_preserves_the_original_quarantine_date(repo):
    _git(repo, "config", "core.quotePath", "true")
    original = "tests/smoke/features/é.feature"
    _commit(repo, original, QUARANTINED, "2026-01-01")
    _git(repo, "mv", original, FEATURE_PATH)
    _git(repo, "commit", "-q", "-m", "rename", when="2026-04-01")

    dates = qa.scenario_quarantine_dates(repo, repo / FEATURE_PATH, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 1, 1), "history")}


def test_history_commit_without_the_file_at_that_path_is_skipped(repo, monkeypatch):
    # A history entry whose `git show <sha>:<path>` fails is skipped, not fatal.
    _commit(repo, "README.md", "x\n", "2026-01-01")
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-02-01")
    readme_only = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=repo, text=True, capture_output=True, check=True,
    ).stdout.strip()
    real_history = qa.file_history_entries

    def history_with_extra_commit(repo_root, feature_file):
        entries = real_history(repo_root, feature_file)
        return [(readme_only, entries[0][1].replace(month=1), FEATURE_PATH)] + entries

    monkeypatch.setattr(qa, "file_history_entries", history_with_extra_commit)

    dates = qa.scenario_quarantine_dates(repo, repo / FEATURE_PATH, {"Flaky thing"})

    assert dates == {"Flaky thing": (date(2026, 2, 1), "history")}


def test_untracked_feature_file_has_no_fallback_date(repo):
    _commit(repo, "README.md", "x\n", "2026-01-01")
    untracked = repo / "tests/smoke/features/new.feature"
    untracked.parent.mkdir(parents=True)
    untracked.write_text(QUARANTINED, encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unable to determine fallback date for tests/smoke/features/new.feature"):
        qa.scenario_quarantine_dates(repo, untracked, {"Flaky thing"})


def test_file_last_modified_date_raises_outside_a_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    feature = tmp_path / "tests/f.feature"
    feature.parent.mkdir()
    feature.write_text(QUARANTINED, encoding="utf-8")

    with pytest.raises(RuntimeError, match="not a git repository"):
        qa.file_last_modified_date(tmp_path, feature)


def test_build_quarantine_entries_from_real_history(repo):
    _commit(repo, FEATURE_PATH, PLAIN, "2026-01-01")
    _commit(repo, FEATURE_PATH, QUARANTINED, "2026-02-01")

    entries = qa.build_quarantine_entries(
        qa.find_quarantined_scenarios(repo),
        today=date(2026, 3, 10),
        max_days=30,
        grace_days=5,
        repo_root=repo,
    )

    assert [(e.feature_file.as_posix(), e.scenario_name, e.age_days, e.threshold_days, e.date_source) for e in entries] == [
        (FEATURE_PATH, "Flaky thing", 37, 35, "history"),
    ]
    assert [e.scenario_name for e in qa.find_expired_quarantines(entries)] == ["Flaky thing"]


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    script = Path(qa.__file__).resolve()
    return subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_fails_on_an_old_quarantine(repo):
    _commit(repo, FEATURE_PATH, QUARANTINED, "2020-01-01")

    result = _run_cli(repo, "--grace-days", "30")

    assert result.returncode == 1, result.stderr
    assert "ERROR: Found 1 @quarantine scenario(s) older than 60 days" in result.stdout
    assert f"Feature file: {FEATURE_PATH}" in result.stdout
    assert "Date quarantined: 2020-01-01" in result.stdout
    assert "Date source: history" in result.stdout


def test_cli_passes_when_nothing_is_quarantined(repo):
    _commit(repo, FEATURE_PATH, PLAIN, "2020-01-01")

    result = _run_cli(repo)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK: no @quarantine scenarios exceed 30 days")
