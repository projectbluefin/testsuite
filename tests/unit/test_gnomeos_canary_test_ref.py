"""The canary must test a pull request head without a maintainer pushing a branch.

Issue #1172 gives ``.github/workflows/gnomeos-canary.yml`` the same
``test_ref`` input the ordinary manual test run already takes, so the canary
can check a contributor's pull request head directly instead of forcing a
maintainer to copy the contributor's code onto a branch in this repository
first. ``workflow_dispatch`` only accepts a branch or tag in this repository,
so without this input canarying a fork pull request meant pushing its head to
a branch such as ``canary/pr-1145`` first. This adds the optional input to
both triggers, points the checkout at ``inputs.test_ref || github.sha``, and
records the commit that was actually checked out as ``testsuite-ref``.

The workflow's token stays ``contents: read`` and no secret is added, so the
canary still runs the pull request's scripts and its ``gnome-e2e`` action on
the runner without gaining write access or credentials (``persist-credentials:
false``).
"""
from pathlib import Path

import yaml

WORKFLOW = ".github/workflows/gnomeos-canary.yml"


def _workflow():
    root = Path(__file__).resolve().parents[2]
    return yaml.safe_load((root / WORKFLOW).read_text())


def _triggers(workflow):
    # YAML 1.1 reads the bare ``on:`` key as the boolean ``True``.
    return workflow[True]


def _checkout_step(workflow):
    steps = workflow["jobs"]["canary"]["steps"]
    return next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))


def _canary_action_step(workflow):
    steps = workflow["jobs"]["canary"]["steps"]
    return next(s for s in steps if s.get("uses", "").endswith("/gnome-e2e"))


def test_test_ref_input_exists_on_both_triggers():
    triggers = _triggers(_workflow())
    for trigger in ("workflow_dispatch", "workflow_call"):
        inputs = triggers[trigger]["inputs"]
        assert "test_ref" in inputs
        ref = inputs["test_ref"]
        assert ref["type"] == "string"
        assert ref["required"] is False
        assert ref["default"] == ""


def test_checkout_uses_test_ref_or_dispatched_commit():
    checkout = _checkout_step(_workflow())
    assert checkout.get("id") == "checkout"
    assert checkout["with"]["ref"] == "${{ inputs.test_ref || github.sha }}"
    assert checkout["with"]["persist-credentials"] is False


def test_testsuite_ref_records_the_checked_out_commit():
    action_step = _canary_action_step(_workflow())
    assert action_step["with"]["testsuite-ref"] == "${{ steps.checkout.outputs.commit }}"


def test_permissions_stay_contents_read_only():
    assert _workflow()["permissions"] == {"contents": "read"}
