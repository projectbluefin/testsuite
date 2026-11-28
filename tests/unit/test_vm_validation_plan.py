"""Unit tests for the candidate-VM change-path policy (scripts/vm_validation_plan.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.vm_validation_plan as vm_validation_plan
from scripts.vm_validation_plan import (
    ACTION,
    ACTION_LANES,
    ADVISORY_SUITES,
    FULL,
    HOSTED_SUITES,
    plan,
    suites_for_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "vm_validation_plan.py"


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/skills/ci-ops/e2e-workflow/SKILL.md",
        "docs/skills/index.json",
        "tests/smoke/README.md",
        "tests/unit/test_image_slug.py",
        "dashboard/index.html",
        "Justfile",
        ".github/workflows/unit-tests.yml",
        ".github/workflows/update-v1-tag.yml",
        "scripts/validate_docs.py",
        "scripts/v1_gate.py",
        "scripts/v1_gate_compare.py",
        "scripts/vm_validation_plan.py",
        "scripts/quarantine_citations.py",
        "scripts/quarantine_followup.py",
        ".github/workflows/quarantine-followup.yml",
    ],
)
def test_paths_that_never_reach_a_vm_need_no_boot(path):
    assert suites_for_path(path) == ()


def test_quarantine_tooling_change_does_not_boot():
    result = plan(
        [
            "scripts/quarantine_citations.py",
            "scripts/quarantine_followup.py",
            ".github/workflows/quarantine-followup.yml",
            ".github/workflows/pr-validate.yml",
            "tests/unit/test_quarantine_followup.py",
        ]
    )
    assert result["vm_required"] is False


def test_check_quarantine_age_still_boots_because_e2e_runs_it():
    # e2e.yml sparse-checks-out scripts/check_quarantine_age.py; the new
    # quarantine scripts importing it does not change that.
    assert suites_for_path("scripts/check_quarantine_age.py") != ()


def test_docs_only_change_does_not_boot():
    result = plan(["README.md", "docs/runbook.md", "tests/unit/test_x.py"])
    assert result["vm_required"] is False
    assert result["suites"] == []


@pytest.mark.parametrize(
    "path, suite",
    [
        ("tests/smoke/features/steps/shell_steps.py", "smoke"),
        ("tests/common/features/environment.py", "common"),
        ("tests/lifecycle/features/upgrade.feature", "lifecycle"),
        ("tests/kde-smoke/features/steps/kde_steps.py", "kde-smoke"),
    ],
)
def test_suite_steps_and_hooks_select_their_own_suite(path, suite):
    assert suites_for_path(path) == (suite,)


def test_shared_gui_helper_needs_gui_and_ssh_lanes():
    assert suites_for_path("tests/shared/wait_for_shell.py") == ("smoke", "common")


def test_shared_ssh_helper_needs_ssh_and_lifecycle_lanes():
    assert suites_for_path("tests/shared/ssh_steps.py") == ("common", "lifecycle")


def test_shared_kde_and_extension_helpers_route_to_their_suites():
    assert suites_for_path("tests/shared/kde_webdriver.py") == ("kde-smoke",)
    assert suites_for_path("tests/shared/extension_session.py") == (ACTION,)


def test_verdict_gate_script_routes_to_kde_gnome_gui_and_action_lanes():
    # The gate guards kde-smoke, the GNOME GUI lanes, and the gnome-e2e
    # composite action, so an edit to it must not fall through to scripts/*
    # and lose kde-smoke or the action lane.
    assert suites_for_path("scripts/assert_passed.py") == ("kde-smoke", "smoke", ACTION)


def test_reusable_workflow_change_requires_full_representative_set():
    assert suites_for_path(".github/workflows/e2e.yml") == FULL
    assert set(FULL) == {"smoke", "common", "lifecycle"}


@pytest.mark.parametrize(
    "path",
    [".github/actions/gnome-e2e/action.yml", "scripts/extension_validation.py"],
)
def test_composite_action_code_maps_to_action_pseudo_lane(path):
    assert suites_for_path(path) == (ACTION,)


def test_composite_action_reported_outside_e2e_suites():
    result = plan(
        [".github/actions/gnome-e2e/action.yml", "scripts/extension_validation.py"]
    )
    assert result["vm_required"] is True
    assert result["suites"] == []
    assert result["no_hosted_lane"] == []
    assert result["composite_action"] == [ACTION]


def test_composite_action_combines_with_e2e_suites():
    result = plan(
        [".github/actions/gnome-e2e/action.yml", "tests/smoke/features/x.feature"]
    )
    assert result["suites"] == ["smoke"]
    assert result["composite_action"] == [ACTION]


def test_runner_image_change_requires_gui_and_ssh():
    assert suites_for_path("container/Containerfile.runner") == ("smoke", "common")
    assert suites_for_path("container/Containerfile.kde-runner") == ("kde-smoke",)


def test_unknown_path_fails_closed_to_full_set():
    assert suites_for_path("some/new/thing.py") == FULL


def test_plan_unions_and_sorts_suites_with_reasons():
    result = plan(
        [
            "tests/smoke/features/steps/a.py",
            "tests/shared/ssh_config.py",
            "docs/x.md",
            "",
        ]
    )
    assert result["vm_required"] is True
    assert result["suites"] == ["common", "lifecycle", "smoke"]
    assert result["reasons"]["docs/x.md"] == []
    assert "" not in result["reasons"]


def test_suite_without_hosted_lane_is_reported_not_dropped():
    result = plan(["tests/hardware/features/steps/udev.py"])
    assert result["vm_required"] is True
    assert result["suites"] == []
    assert result["no_hosted_lane"] == ["hardware"]
    assert result["composite_action"] == []


def test_every_mapped_suite_is_known():
    for path in [
        ".github/workflows/e2e.yml",
        ".github/actions/gnome-e2e/action.yml",
        ".github/workflows/iso-validation.yml",
        "scripts/extension_validation.py",
        "tests/shared/screenshot.py",
    ]:
        assert set(suites_for_path(path)) <= HOSTED_SUITES | ACTION_LANES


def test_cli_reads_stdin_and_prints_json():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input="tests/common/features/environment.py\nREADME.md\n",
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out["suites"] == ["common"]
    assert out["vm_required"] is True


def test_cli_accepts_path_arguments():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "docs/runbook.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout)["vm_required"] is False


@pytest.mark.parametrize(
    "path",
    [
        "tests/extensions/features/steps/lifecycle_steps.py",
        "tests/extensions/features/just_perfection.feature",
        "tests/shared/gnome_extensions_artifacts.py",
        "scripts/build_extension_artifact.py",
        "scripts/stage_extension.py",
        ".github/workflows/extension-validation.yml",
    ],
)
def test_extension_paths_never_boot_in_e2e_yml(path):
    # The extensions suite's before_all refuses a non-disposable guest, so a
    # PR touching it must not ask e2e.yml to boot it (run 43614202176).
    assert suites_for_path(path) == (ACTION,)
    result = plan([path], pr=True)
    assert "extensions" not in result["suites"]
    assert result["composite_action"] == [ACTION]


CHAIRLIFT_PATHS = [
    "tests/chairlift/features/chairlift.feature",
    "tests/chairlift/features/steps/steps.py",
    "tests/chairlift/features/environment.py",
    "tests/chairlift/polkit_tty_agent.py",
    ".github/workflows/chairlift-scheduled.yml",
]


def test_chairlift_is_the_only_advisory_suite_and_is_never_hosted():
    assert set(ADVISORY_SUITES) == {"chairlift"}
    assert not set(ADVISORY_SUITES) & HOSTED_SUITES
    assert all("gates nothing" in why for why in ADVISORY_SUITES.values())


@pytest.mark.parametrize("pr", [False, True])
def test_chairlift_only_change_boots_nothing_and_says_why(pr):
    for path in CHAIRLIFT_PATHS:
        assert suites_for_path(path) == ("chairlift",)
    result = plan(CHAIRLIFT_PATHS, pr=pr)
    assert result["vm_required"] is False
    assert result["suites"] == []
    assert result["no_hosted_lane"] == []
    assert result["composite_action"] == []
    assert result["advisory"] == {"chairlift": ADVISORY_SUITES["chairlift"]}
    assert "chairlift-scheduled.yml" in result["advisory"]["chairlift"]
    # The path still names the suite it belongs to, for the reader.
    assert result["reasons"]["tests/chairlift/features/steps/steps.py"] == ["chairlift"]
    if pr:
        assert result["canary"] is False


@pytest.mark.parametrize("pr", [False, True])
def test_chairlift_with_a_hosted_suite_still_gates_the_hosted_suite(pr):
    result = plan(["tests/chairlift/features/steps/steps.py", "tests/smoke/features/x.feature"], pr=pr)
    assert result["vm_required"] is True
    assert result["suites"] == ["smoke"]
    assert result["no_hosted_lane"] == []
    assert set(result["advisory"]) == {"chairlift"}
    # A suite with no hosted lane still holds next to it.
    held = plan(["tests/chairlift/features/x.feature", "tests/hardware/features/x.feature"], pr=pr)
    assert held["no_hosted_lane"] == ["hardware"]
    assert "chairlift" not in held["no_hosted_lane"] + held["suites"]


def _repo_paths() -> list[str]:
    skip = {".git", ".worktrees", "__pycache__", ".pytest_cache", "node_modules"}
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.rglob("*")
        if path.is_file() and not skip & set(path.relative_to(REPO_ROOT).parts)
    )


@pytest.mark.parametrize("pr", [False, True])
def test_advisory_suites_move_no_other_path(monkeypatch, pr):
    # Every path in the repo outside the advisory suite plans exactly as it
    # did before advisory suites existed, alone and all together.
    others = [p for p in _repo_paths() if "chairlift" not in p]
    others += ["unknown-base", "some/new/thing.py", "tests/hardware/features/x.feature"]
    with_advisory = [plan([p], pr=pr) for p in others]
    together = plan(others, pr=pr)
    monkeypatch.setattr(vm_validation_plan, "ADVISORY_SUITES", {})
    assert [plan([p], pr=pr) for p in others] == with_advisory
    assert plan(others, pr=pr) == together
    assert not any("advisory" in result for result in with_advisory)
