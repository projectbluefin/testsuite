"""Unit tests for the v1 gate's pin-bump filter (scripts/v1_gate_pins.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.v1_gate import decide
from scripts.v1_gate_pins import is_pin_bump
from scripts.vm_validation_plan import plan

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "v1_gate_pins.py"

OLD = "41992083f437357010da2ea072ef353d982ae369"
NEW = "6453818aa0d0c3b54c9f5e1e0cf2a1f2b9f6b1c2"
ACTION = ".github/actions/gnome-e2e/action.yml"


def _diff(*lines: str) -> str:
    return "\n".join([f"--- a/{ACTION}", f"+++ b/{ACTION}", "@@ -108 +108 @@", *lines])


def test_renovate_digest_swap_is_a_pin_bump():
    diff = _diff(
        f"-      uses: projectbluefin/actions/bootc-build/setup-runner@{OLD} # v1",
        f"+      uses: projectbluefin/actions/bootc-build/setup-runner@{NEW} # v1",
    )
    assert is_pin_bump(diff)


def test_list_item_uses_and_changed_comment_still_count():
    diff = _diff(
        f"-    - uses: actions/checkout@{OLD} # v6",
        f"+    - uses: actions/checkout@{NEW} # v7",
    )
    assert is_pin_bump(diff)


def test_a_different_action_is_not_a_pin_bump():
    diff = _diff(
        f"-      uses: projectbluefin/actions/bootc-build/setup-runner@{OLD} # v1",
        f"+      uses: someone/else/setup-runner@{NEW} # v1",
    )
    assert not is_pin_bump(diff)


def test_a_tag_or_branch_ref_is_not_a_pin_bump():
    diff = _diff(
        f"-      uses: actions/checkout@{OLD} # v7",
        "+      uses: actions/checkout@v7",
    )
    assert not is_pin_bump(diff)


def test_any_other_changed_line_keeps_the_file():
    diff = _diff(
        f"-      uses: actions/checkout@{OLD} # v7",
        f"+      uses: actions/checkout@{NEW} # v7",
        "+        sudo podman run --rm something",
    )
    assert not is_pin_bump(diff)


def test_same_sha_or_empty_diff_is_not_a_pin_bump():
    same = _diff(
        f"-      uses: actions/checkout@{OLD} # v7",
        f"+      uses: actions/checkout@{OLD} # v7 again",
    )
    assert not is_pin_bump(same)
    assert not is_pin_bump("")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return _git(repo, "rev-parse", "HEAD")


def _run_filter(repo: Path, previous: str, sha: str, paths: list[str]):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), previous, sha],
        cwd=repo,
        input="\n".join(paths) + "\n",
        check=True,
        capture_output=True,
        text=True,
    )


def _action(ref: str, extra: str = "") -> str:
    return (
        "runs:\n  using: composite\n  steps:\n"
        f"    - uses: projectbluefin/actions/bootc-build/setup-runner@{ref} # v1\n"
        f"    - run: echo hi{extra}\n"
    )


def test_cli_drops_a_pin_only_action_change_and_the_gate_moves(tmp_path):
    _git(tmp_path, "init", "-q")
    previous = _commit(tmp_path, {ACTION: _action(OLD), "README.md": "x\n"})
    sha = _commit(tmp_path, {ACTION: _action(NEW), "README.md": "y\n"})

    result = _run_filter(tmp_path, previous, sha, [ACTION, "README.md"])

    assert result.stdout.split() == ["README.md"]
    assert f"pin bump only, no VM needed: {ACTION}" in result.stderr
    assert decide(plan(result.stdout.split()))["action"] == "move"


def test_cli_keeps_an_action_change_that_is_more_than_a_pin(tmp_path):
    # Kept for the gate, which runs the GNOME OS canary on it (not a move).
    _git(tmp_path, "init", "-q")
    previous = _commit(tmp_path, {ACTION: _action(OLD)})
    sha = _commit(tmp_path, {ACTION: _action(NEW, extra=" there")})

    result = _run_filter(tmp_path, previous, sha, [ACTION])

    assert result.stdout.split() == [ACTION]
    assert decide(plan(result.stdout.split()))["action"] == "canary"


def test_cli_leaves_pin_bumps_outside_the_action_to_the_plan(tmp_path):
    workflow = ".github/workflows/e2e.yml"
    _git(tmp_path, "init", "-q")
    previous = _commit(tmp_path, {workflow: _action(OLD)})
    sha = _commit(tmp_path, {workflow: _action(NEW)})

    result = _run_filter(tmp_path, previous, sha, [workflow])

    assert result.stdout.split() == [workflow]


def test_the_filter_itself_never_reaches_a_vm():
    assert plan(["scripts/v1_gate_pins.py"])["vm_required"] is False
