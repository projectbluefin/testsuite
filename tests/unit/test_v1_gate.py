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


def test_composite_action_change_holds_v1():
    d = decide(
        plan([".github/actions/gnome-e2e/action.yml", "tests/smoke/features/x.feature"])
    )
    assert d["action"] == "hold"
    assert d["suites"] == ""
    assert "gnome-e2e-action" in d["reason"]


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
    assert all("=" in line for line in out)
