"""Unit tests for ``tests.shared.failed_setup``.

The marker file is what keeps ``scripts/all_skipped.py`` from turning a
``before_all`` harness failure into a green screenshot gate, so every recorder
path is covered here.
"""

import os
from types import SimpleNamespace

import pytest

from tests.shared.failed_setup import (
    MARKER_FILENAME,
    record_failed_setup,
    write_failed_setup_marker,
)


class _Config:
    def __init__(self, results_dir=None):
        self.userdata = {"results_dir": results_dir} if results_dir else {}


def _context(results_dir=None):
    return SimpleNamespace(config=_Config(results_dir))


def test_write_marker_creates_file(tmp_path):
    context = _context(str(tmp_path / "results"))
    path = write_failed_setup_marker(context, "boom")
    assert path == str(tmp_path / "results" / MARKER_FILENAME)
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as handle:
        assert handle.read() == "boom"


def test_write_marker_creates_missing_results_dir(tmp_path):
    target = tmp_path / "deep" / "results"
    write_failed_setup_marker(_context(str(target)), "boom")
    assert (target / MARKER_FILENAME).is_file()


def test_write_marker_overwrites_previous_content(tmp_path):
    context = _context(str(tmp_path))
    write_failed_setup_marker(context, "first")
    write_failed_setup_marker(context, "second")
    assert (tmp_path / MARKER_FILENAME).read_text(encoding="utf-8") == "second"


def test_write_marker_uses_env_var_when_no_userdata(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTSUITE_RESULTS_DIR", str(tmp_path / "env-results"))
    path = write_failed_setup_marker(None, "boom")
    assert path == str(tmp_path / "env-results" / MARKER_FILENAME)


def test_write_marker_returns_none_on_oserror(tmp_path, capsys):
    blocker = tmp_path / "results"
    blocker.write_text("not a directory", encoding="utf-8")
    assert write_failed_setup_marker(_context(str(blocker)), "boom") is None
    assert "could not write" in capsys.readouterr().out


def test_record_sets_attribute_and_writes_marker(tmp_path):
    context = _context(str(tmp_path))
    assert record_failed_setup(context, "traceback text") == "traceback text"
    assert context.failed_setup == "traceback text"
    assert (tmp_path / MARKER_FILENAME).read_text(encoding="utf-8") == "traceback text"


def test_record_still_sets_attribute_when_marker_unwritable(tmp_path):
    blocker = tmp_path / "results"
    blocker.write_text("not a directory", encoding="utf-8")
    context = _context(str(blocker))
    record_failed_setup(context, "traceback text")
    assert context.failed_setup == "traceback text"


@pytest.mark.parametrize("suite", [
    "tests/smoke/features/environment.py",
    "tests/developer/features/environment.py",
    "tests/software/features/environment.py",
    "tests/vanilla-gnome/features/environment.py",
    "tests/bazzite/features/environment.py",
    "tests/kde-smoke/features/environment.py",
    "tests/chairlift/features/environment.py",
])
def test_every_failed_setup_assignment_writes_the_marker(suite):
    """A bare ``failed_setup`` assignment re-opens the harness-failure hole."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lines = open(os.path.join(repo_root, suite), encoding="utf-8").read().splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        is_assignment = (
            stripped.startswith("context.failed_setup =")
            or stripped.startswith('context.kde["failed_setup"] =')
        )
        if not is_assignment:
            continue
        window = "\n".join(lines[index:index + 3])
        assert "write_failed_setup_marker(" in window, (
            f"{suite}:{index + 1} assigns failed_setup without writing the marker"
        )
