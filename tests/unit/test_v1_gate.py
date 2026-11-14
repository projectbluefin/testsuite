"""Unit tests for the post-merge v1 gate decision (scripts/v1_gate.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.v1_gate import UNGATED_SUITES, decide
from scripts.vm_validation_plan import plan

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "v1_gate.py"


def test_docs_only_range_moves_without_booting():
    d = decide(plan(["README.md", "docs/skills/index.json"]))
    assert d["action"] == "move"
    assert d["suites"] == ""


def test_suite_change_gates_on_that_suite():
    d = decide(plan(["tests/smoke/features/steps/apps.py"]))
    assert d["action"] == "gate"
    assert d["suites"] == "smoke"
    assert d["ungated"] == ""


def test_reusable_workflow_change_boots_gui_and_ssh_but_reports_lifecycle():
    d = decide(plan([".github/workflows/e2e.yml"]))
    assert d["action"] == "gate"
    assert d["suites"] == "common,smoke"
    assert d["ungated"] == "lifecycle"
    assert "not gated: lifecycle" in d["reason"]


def test_unknown_path_fails_closed_to_a_gate_not_a_move():
    d = decide(plan(["something/new.txt"]))
    assert d["action"] == "gate"
    assert set(d["suites"].split(",")) == {"smoke", "common"}


def test_lifecycle_only_change_moves_and_says_why():
    d = decide(plan(["tests/lifecycle/features/steps/steps.py"]))
    assert d["action"] == "move"
    assert d["ungated"] == "lifecycle"
    assert "#706" in d["reason"]


def test_composite_action_change_runs_the_canary_instead_of_holding():
    d = decide(plan([".github/actions/gnome-e2e/action.yml"]))
    assert d["action"] == "canary"
    assert d["canary"] == "true"
    assert d["suites"] == ""
    assert "canary" in d["reason"]


def test_composite_action_and_suite_change_boots_and_runs_the_canary():
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml", "tests/smoke/features/x.feature"])
    )
    assert d["action"] == "gate"
    assert d["suites"] == "smoke"
    assert d["canary"] == "true"


def test_action_lane_script_the_canary_does_not_run_still_holds():
    # The action's assert_passed.py gate step skips the gnomeos-canary suite
    # (action.yml `if: ... inputs.suite != 'gnomeos-canary'`), so a canary pass
    # says nothing about it.
    for paths in (
        ["scripts/assert_passed.py"],
        [".github/actions/gnome-e2e/action.yml", "scripts/assert_passed.py"],
    ):
        d = decide(plan(paths))
        assert d["action"] == "hold"
        assert d["canary"] == "false"
        assert "gnome-e2e-action" in d["reason"]


def test_extension_validation_is_covered_by_the_canary():
    # action.yml runs scripts/extension_validation.py for the canary suite too.
    d = decide(plan(["scripts/extension_validation.py"]))
    assert d["action"] == "canary"
    assert d["canary"] == "true"


def test_changed_steps_the_canary_skips_keep_the_hold():
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml"]),
        canary_gaps=("Mandatory-coverage gate",),
    )
    assert d["action"] == "hold"
    assert d["canary"] == "false"
    assert "Mandatory-coverage gate" in d["reason"]


def test_leading_dot_slash_paths_are_still_covered():
    d = decide(plan(["./.github/actions/gnome-e2e/action.yml"]))
    assert d["canary"] == "true"


def test_cli_reads_canary_gaps_from_the_environment():
    plan_json = json.dumps(plan([".github/actions/gnome-e2e/action.yml"]))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/v1_gate.py")],
        input=plan_json,
        capture_output=True,
        text=True,
        check=True,
        env={"V1_GATE_CANARY_GAPS": "Mandatory-coverage gate\nOther step", "PATH": "/usr/bin:/bin"},
    )
    assert "action=hold" in result.stdout.splitlines()
    assert "Other step" in result.stdout


def test_no_canary_without_an_action_change():
    for paths in (["README.md"], ["tests/common/features/steps/ssh.py"]):
        assert decide(plan(paths))["canary"] == "false"


def test_suite_without_hosted_lane_holds_v1():
    d = decide(plan(["tests/hardware/features/steps/gpu.py"]))
    assert d["action"] == "hold"
    assert "hardware" in d["reason"]


def test_only_lifecycle_is_ungated():
    assert UNGATED_SUITES == frozenset({"lifecycle"})


def test_gate_script_itself_never_reaches_a_vm():
    assert decide(plan(["scripts/v1_gate.py"]))["action"] == "move"


def test_cli_prints_github_output_lines():
    stdin = json.dumps(plan(["tests/common/features/steps/ssh.py"]))
    out = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert out[0] == "action=gate"
    assert "suites=common" in out
    assert "canary=false" in out
    assert all("=" in line for line in out)


# ---------------------------------------------------------------------------
# Extension-staging changes run extension-validation.yml (#1218)
# ---------------------------------------------------------------------------

EXTENSION_PATHS = [
    "scripts/stage_extension.py",
    "scripts/build_extension_artifact.py",
    ".github/workflows/extension-validation.yml",
    "tests/extensions/features/steps/lifecycle_steps.py",
    "tests/shared/gnome_extensions_artifacts.py",
]


def test_extension_staging_change_runs_extension_validation_not_a_hold():
    for path in EXTENSION_PATHS:
        d = decide(plan([path]), extension_gaps=())
        assert d["action"] == "canary", path
        assert d["extensions"] == "true", path
        assert d["canary"] == "false", path
        assert "extension validation" in d["reason"], path


def test_extension_and_action_change_run_both():
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml", "scripts/stage_extension.py"]),
        extension_gaps=(),
    )
    assert d["action"] == "canary"
    assert d["canary"] == "true"
    assert d["extensions"] == "true"


def test_action_steps_only_the_extension_suite_runs_are_covered_by_it():
    # The canary skips an extensions-only step; an extension run executes it.
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml"]),
        canary_gaps=("Stage the extension candidate",),
        extension_gaps=(),
    )
    assert d["action"] == "canary"
    assert d["canary"] == "true"
    assert d["extensions"] == "true"


def test_steps_neither_run_executes_still_hold():
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml"]),
        canary_gaps=("Mandatory-coverage gate",),
        extension_gaps=("Mandatory-coverage gate",),
    )
    assert d["action"] == "hold"
    assert d["extensions"] == "false"
    assert "Mandatory-coverage gate" in d["reason"]


def test_without_extension_gaps_the_extension_run_covers_no_action_step():
    # An older caller that never computed --with-extensions keeps the hold.
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml"]),
        canary_gaps=("Stage the extension candidate",),
    )
    assert d["action"] == "hold"


def test_no_extension_run_without_an_extension_change():
    d = decide(plan([".github/actions/gnome-e2e/action.yml"]), extension_gaps=())
    assert d["extensions"] == "false"
    d = decide(plan(["tests/smoke/features/x.feature"]), extension_gaps=())
    assert d["extensions"] == "false"
    assert d["canary"] == "false"


def test_extension_change_with_a_suite_change_gates_and_validates():
    d = decide(plan(["scripts/stage_extension.py", "tests/smoke/features/x.feature"]), extension_gaps=())
    assert d["action"] == "gate"
    assert d["suites"] == "smoke"
    assert d["extensions"] == "true"


def test_cli_reads_extension_gaps_from_the_environment():
    plan_json = json.dumps(plan([".github/actions/gnome-e2e/action.yml"]))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/v1_gate.py")],
        input=plan_json,
        capture_output=True,
        text=True,
        check=True,
        env={
            "V1_GATE_CANARY_GAPS": "Stage the extension candidate",
            "V1_GATE_EXTENSION_GAPS": "",
            "PATH": "/usr/bin:/bin",
        },
    )
    lines = result.stdout.splitlines()
    assert "action=canary" in lines
    assert "extensions=true" in lines
