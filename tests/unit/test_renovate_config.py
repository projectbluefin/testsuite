"""Unit tests for renovate.json: every pinned requirements file is one Renovate reads."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((REPO_ROOT / "renovate.json").read_text())

# Renovate's built-in file pattern for the pip_requirements manager. Entries in
# the repo's managerFilePatterns are added to this one; they do not replace it.
DEFAULT_PIP_PATTERN = r"(^|/)[\w-]*requirements([-._]\w+)?\.(txt|pip)$"


def _pip_patterns() -> list[str]:
    extra = CONFIG.get("pip_requirements", {}).get("managerFilePatterns", [])
    for pattern in extra:
        assert pattern.startswith("/") and pattern.endswith("/"), (
            f"managerFilePatterns entry {pattern!r} must be a /regex/ so Renovate "
            "treats it as a pattern, not a glob"
        )
    return [DEFAULT_PIP_PATTERN, *(p[1:-1] for p in extra)]


def _matched(path: str) -> bool:
    return any(re.search(pattern, path) for pattern in _pip_patterns())


def test_every_requirements_file_is_managed_by_renovate():
    files = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in REPO_ROOT.glob("container/requirements*.txt")
    )
    assert files, "expected at least one container/requirements*.txt"
    unmanaged = [f for f in files if not _matched(f)]
    assert not unmanaged, f"Renovate's pip_requirements manager skips: {unmanaged}"


def test_kde_runner_requirements_needs_the_explicit_pattern():
    # The hyphen in ".kde-runner" stops the default pattern's \w+, which is why
    # the file needs its own managerFilePatterns entry.
    path = "container/requirements.kde-runner.txt"
    assert not re.search(DEFAULT_PIP_PATTERN, path)
    assert _matched(path)
