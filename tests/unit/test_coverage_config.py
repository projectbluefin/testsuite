"""Contract tests for .coveragerc, which configures the unit-test coverage gate."""

from __future__ import annotations

from pathlib import Path

import coverage
from coverage.files import find_python_files

REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGERC = REPO_ROOT / ".coveragerc"


def _config():
    return coverage.Coverage(config_file=str(COVERAGERC))


def test_worker_and_subprocess_data_is_collected():
    cov = _config()
    assert cov.get_option("run:parallel") is True
    assert "subprocess" in cov.get_option("run:patch")


def test_report_includes_namespace_packages():
    # Suite directories such as tests/kde-smoke/ have hyphens and no
    # __init__.py, so coverage only reports their never-imported step files
    # (at 0%) when namespace packages are included.
    assert _config().get_option("report:include_namespace_packages") is True


def test_never_imported_suite_files_are_discoverable():
    include_ns = _config().get_option("report:include_namespace_packages")
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
