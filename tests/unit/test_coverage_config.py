"""Contract tests for .coveragerc, which configures the unit-test coverage gate."""

from __future__ import annotations

import configparser
from pathlib import Path

from coverage.files import find_python_files

REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGERC = REPO_ROOT / ".coveragerc"

# Read the file directly: constructing coverage.Coverage() inside a measured
# pytest worker replaces that worker's collector and loses its data.


def _config():
    parser = configparser.ConfigParser()
    parser.read(COVERAGERC)
    return parser


def test_worker_and_subprocess_data_is_collected():
    cfg = _config()
    assert cfg.getboolean("run", "parallel")
    assert "subprocess" in cfg.get("run", "patch").split()


def test_report_includes_namespace_packages():
    # Suite directories such as tests/kde-smoke/ have hyphens and no
    # __init__.py, so coverage only reports their never-imported step files
    # (at 0%) when namespace packages are included.
    assert _config().getboolean("report", "include_namespace_packages")


def test_never_imported_suite_files_are_discoverable():
    include_ns = _config().getboolean(
        "report", "include_namespace_packages", fallback=False
    )
    found = {
        Path(p).resolve()
        for p in find_python_files(str(REPO_ROOT / "tests"), include_ns)
    }
    for rel in (
        "tests/kde-smoke/features/steps/steps.py",
        "tests/gnomeos-canary/features/steps/canary_steps.py",
        "tests/vanilla-gnome/features/environment.py",
    ):
        assert (REPO_ROOT / rel).resolve() in found, rel
