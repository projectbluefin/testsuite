"""Exercise runner image change detection against real Git trees."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/runner-image-changes.sh"


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["unrelated.txt"], "runner=false\nkde=false"),
        (["container/Containerfile.runner"], "runner=true\nkde=false"),
        ([".github/workflows/build-runner.yml"], "runner=true\nkde=false"),
        (["container/Containerfile.kde-runner"], "runner=false\nkde=true"),
        (["container/requirements.kde-runner.txt"], "runner=false\nkde=true"),
        ([".github/workflows/build-kde-runner.yml"], "runner=false\nkde=true"),
        (["container/Containerfile.runner", "container/Containerfile.kde-runner"],
         "runner=true\nkde=true"),
    ],
)
def test_detects_changed_image_inputs(tmp_path, paths, expected):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "commit", "--allow-empty", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    for path in paths:
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("changed\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "change")
    result = subprocess.run(
        ["bash", str(SCRIPT), base], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == expected


def test_invalid_base_fails_closed(tmp_path):
    git(tmp_path, "init")
    result = subprocess.run(
        ["bash", str(SCRIPT), "missing"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
