"""Changed gnome-e2e action steps that the GNOME OS canary skips (#1196 review).

The canary runs the action with suite=gnomeos-canary, so a step whose `if:`
excludes that suite is not covered by a canary pass and must keep the v1 hold.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from scripts.v1_gate_canary_scope import canary_skips, gaps

REPO_ROOT = Path(__file__).resolve().parents[2]


def _action(steps):
    return yaml.safe_dump({"name": "gnome-e2e", "runs": {"using": "composite", "steps": steps}})


SHARED = {"name": "Boot", "shell": "bash", "run": "boot"}
GATE = {
    "name": "Mandatory-coverage gate",
    "if": "always() && inputs.suite != 'extensions' && inputs.suite != 'gnomeos-canary'",
    "shell": "bash",
    "run": "assert",
}
EXT = {
    "name": "Extension gate",
    "if": "always() && (inputs.suite == 'extensions' || inputs.suite == 'gnomeos-canary')",
    "shell": "bash",
    "run": "ext",
}
EXT_ONLY = {"name": "Extensions only", "if": "inputs.suite == 'extensions'", "shell": "bash", "run": "x"}


def test_skip_conditions():
    assert canary_skips(GATE)
    assert canary_skips(EXT_ONLY)
    assert not canary_skips(EXT)
    assert not canary_skips(SHARED)
    assert canary_skips({"if": 'inputs.suite != "gnomeos-canary"'})


def test_change_to_a_step_the_canary_runs_is_covered():
    base = _action([SHARED, GATE, EXT])
    head = _action([{**SHARED, "run": "boot2"}, GATE, {**EXT, "run": "ext2"}])
    assert gaps(base, head) == []


def test_change_to_a_step_the_canary_skips_is_a_gap():
    base = _action([SHARED, GATE])
    head = _action([SHARED, {**GATE, "run": "assert2"}])
    assert gaps(base, head) == ["Mandatory-coverage gate"]


def test_added_and_removed_skipped_steps_are_gaps():
    assert gaps(_action([SHARED]), _action([SHARED, EXT_ONLY])) == ["Extensions only"]
    assert gaps(_action([SHARED, GATE]), _action([SHARED])) == ["Mandatory-coverage gate (removed)"]


def test_unchanged_action_has_no_gaps():
    text = _action([SHARED, GATE, EXT])
    assert gaps(text, text) == []


def test_real_action_assert_passed_step_skips_the_canary():
    doc = yaml.safe_load((REPO_ROOT / ".github/actions/gnome-e2e/action.yml").read_text())
    steps = doc["runs"]["steps"]
    assert_steps = [s for s in steps if "assert_passed.py" in str(s.get("run", ""))]
    ext_steps = [s for s in steps if "extension_validation.py" in str(s.get("run", ""))]
    assert assert_steps and all(canary_skips(s) for s in assert_steps)
    assert ext_steps and not any(canary_skips(s) for s in ext_steps)


def test_cli_on_this_repository_head_against_itself_prints_nothing():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/v1_gate_canary_scope.py"), "HEAD", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
