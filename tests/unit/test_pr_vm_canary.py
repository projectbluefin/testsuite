"""PR-only GNOME OS canary routing and workflow contract."""

from pathlib import Path

import pytest
import yaml

from scripts.vm_validation_plan import ACTION, FULL, plan, suites_for_path
from scripts.v1_gate import decide


@pytest.mark.parametrize("path", [
    ".github/workflows/gnomeos-canary.yml",
    "container/Containerfile.gnomeos-harness",
    "container/gnomeos-harness-identity.py",
    "scripts/build-gnomeos-harness.sh",
    "scripts/configure_gnomeos_canary_shell.py",
    "tests/shared/gnomeos_canary.py",
    "tests/gnomeos-canary/features/canary.feature",
])
def test_canary_paths_use_only_canary_on_pr(path):
    result = plan([path], pr=True)
    assert result["reasons"][path] == ["gnomeos-canary"]
    assert result["canary"] is True
    assert result["suites"] == []
    assert result["no_hosted_lane"] == []
    assert result["composite_action"] == []


def test_composite_action_runs_canary_without_losing_other_suites():
    path = ".github/actions/gnome-e2e/action.yml"
    assert suites_for_path(path) == (ACTION,)
    result = plan([path, "tests/smoke/features/test.feature"], pr=True)
    # The action lane stays in the plan; the gate applies the same coverage
    # rule on a PR as after merge.
    assert result["composite_action"] == [ACTION]
    assert result["suites"] == ["smoke"]
    decision = decide(result)
    assert decision["action"] == "gate"
    assert decision["canary"] == "true"


def test_pr_and_post_merge_agree_on_action_lane_scripts():
    for path, action in (
        ("scripts/extension_validation.py", "canary"),
        ("scripts/assert_passed.py", "hold"),
    ):
        assert decide(plan([path], pr=True))["action"] == action
        assert decide(plan([path]))["action"] == action


def test_unrelated_and_unhosted_paths_do_not_run_canary():
    assert not plan(["README.md"], pr=True)["canary"]
    result = plan(["tests/hardware/features/test.feature"], pr=True)
    assert not result["canary"]
    assert result["no_hosted_lane"] == ["hardware"]
    assert decide(result)["action"] == "hold"


def test_workflow_change_exercises_its_canary():
    result = plan([".github/workflows/pr-vm-check.yml"], pr=True)
    assert result["canary"]
    assert set(result["suites"]) == set(FULL)


def test_post_merge_plan_is_unchanged():
    assert plan(["tests/gnomeos-canary/features/canary.feature"])["no_hosted_lane"] == ["gnomeos-canary"]
    # The v1 gate runs the canary for its own suite instead of holding.
    decision = decide(plan(["tests/gnomeos-canary/features/canary.feature"]))
    assert decision["action"] == "canary"
    assert decision["canary"] == "true"
    assert decide(plan([".github/workflows/gnomeos-canary.yml"]))["suites"] == "common,smoke"


def test_pr_workflow_calls_canary_using_plan_output():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/pr-vm-check.yml"
    jobs = yaml.safe_load(path.read_text())["jobs"]
    canary = jobs["canary"]
    assert canary["uses"] == "./.github/workflows/gnomeos-canary.yml"
    assert canary["needs"] == "plan"
    assert canary["if"] == "needs.plan.outputs.canary == 'true'"
    assert canary["permissions"] == {"contents": "read"}
    assert jobs["plan"]["outputs"]["canary"] == "${{ steps.plan.outputs.canary }}"


def test_pr_plan_canary_flag_reaches_the_gate_output():
    decision = decide(plan(["tests/shared/gnomeos_canary.py"], pr=True))
    assert decision["canary"] == "true"
    assert decision["action"] == "canary"
