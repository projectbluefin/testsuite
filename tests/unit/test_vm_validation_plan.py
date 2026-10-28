"""Unit tests for the candidate-VM change-path policy (scripts/vm_validation_plan.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.vm_validation_plan import (
    ACTION,
    ACTION_LANES,
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
    ],
)
def test_paths_that_never_reach_a_vm_need_no_boot(path):
    assert suites_for_path(path) == ()


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
    assert suites_for_path("tests/shared/extension_session.py") == ("extensions",)


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
