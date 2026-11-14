"""Run the v1 gate's "Move or hold v1" shell step with a stubbed ``gh``.

Checks which labels a held v1 issue gets (#1132, #1151): a hand-check hold is
flagged for a maintainer at once and turns urgent after a day, like the other
holds.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "update-v1-tag.yml"

# Logs each call; answers the issue lookups the step makes.
STUB_GH = """#!/bin/bash
echo "gh $*" >> "$GH_LOG"
case "$1 $2" in
  "issue list") [ -n "$STUB_HELD" ] && echo "$STUB_HELD" ;;
  "issue view") echo "$STUB_OPENED" ;;
  "issue create") echo "https://example.invalid/issues/1200" ;;
esac
exit 0
"""


def _step_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["publish"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Move or hold v1")


def _run(tmp_path: Path, **env: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    script = tmp_path / "step.sh"
    script.write_text(_step_script())

    base = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "REPO": "o/r",
        "PREVIOUS": "a" * 40,
        "SHA": "b" * 40,
        "ACTION": "hold",
        "REASON": "the change needs lanes e2e.yml cannot boot (security)",
        "HELD_TITLE": "v1 tag held by the post-merge VM gate",
        "RUN_URL": "https://example.invalid/run",
        "STUB_HELD": "",
        "STUB_OPENED": "",
        # The rest of the publish job's env (the step runs with set -u).
        "ACTOR": "maintainer",
        "SUITES": "",
        "UNGATED": "",
        "IMAGE": "",
        "BASELINE_IMAGE": "",
        "FORCE_REASON": "",
        "GATE_RESULT": "skipped",
        "BASELINE_RESULT": "skipped",
        "COMPARE": "",
        "INFRA": "",
    }
    subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={**base, **env},
        check=False,
        capture_output=True,
        text=True,
    )
    return log.read_text().splitlines()


def _labels(calls: list[str]) -> set[str]:
    added = set()
    for call in calls:
        parts = call.split()
        if parts[:3] == ["gh", "issue", "edit"] and "--add-label" in parts:
            added.add(parts[parts.index("--add-label") + 1])
    return added


def _opened(hours_ago: int) -> str:
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_fresh_hand_check_hold_needs_a_maintainer_but_is_not_urgent(tmp_path):
    calls = _run(tmp_path, STUB_HELD="1149", STUB_OPENED=_opened(1))
    assert _labels(calls) == {"needs-human"}


def test_hand_check_hold_older_than_a_day_turns_urgent(tmp_path):
    calls = _run(tmp_path, STUB_HELD="1149", STUB_OPENED=_opened(48))
    assert _labels(calls) == {"needs-human", "priority/critical-urgent"}


def test_fresh_failed_gate_is_not_escalated(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="gate",
        GATE_RESULT="failure",
        BASELINE_RESULT="failure",
        STUB_HELD="1149",
        STUB_OPENED=_opened(1),
    )
    assert _labels(calls) == set()


def test_failed_gate_older_than_a_day_turns_urgent(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="gate",
        GATE_RESULT="failure",
        BASELINE_RESULT="failure",
        STUB_HELD="1149",
        STUB_OPENED=_opened(48),
    )
    assert _labels(calls) == {"needs-human", "priority/critical-urgent"}


def test_infrastructure_failure_is_urgent_at_once(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="gate",
        GATE_RESULT="failure",
        BASELINE_RESULT="failure",
        INFRA="true",
    )
    assert _labels(calls) == {"needs-human", "priority/critical-urgent"}


def test_move_closes_the_held_issue_without_labels(tmp_path):
    calls = _run(tmp_path, ACTION="move", REASON="docs only", STUB_HELD="1149")
    assert _labels(calls) == set()
    assert any(c.startswith("gh issue close 1149") for c in calls)
    assert any(c.startswith("gh api -X PATCH") for c in calls)


def _moved(calls: list[str]) -> bool:
    return any(c.startswith("gh api -X PATCH") for c in calls)


def test_passed_canary_moves_v1_and_closes_the_held_issue(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="canary",
        CANARY="true",
        CANARY_RESULT="success",
        STUB_HELD="1149",
    )
    assert _moved(calls)
    assert any(c.startswith("gh issue close 1149") for c in calls)
    summary = (tmp_path / "summary.md").read_text()
    assert "GNOME OS desktop canary passed" in summary


def test_failed_canary_holds_v1(tmp_path):
    calls = _run(tmp_path, ACTION="canary", CANARY="true", CANARY_RESULT="failure")
    assert not _moved(calls)
    assert any(c.startswith("gh issue create") for c in calls)


def test_passed_gate_with_failed_canary_holds_v1(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="gate",
        GATE_RESULT="success",
        CANARY="true",
        CANARY_RESULT="failure",
    )
    assert not _moved(calls)


def test_passed_gate_waits_for_a_passing_canary(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="gate",
        GATE_RESULT="success",
        CANARY="true",
        CANARY_RESULT="success",
    )
    assert _moved(calls)


def test_passed_extension_validation_moves_v1(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="canary",
        CANARY="false",
        CANARY_RESULT="skipped",
        EXTENSIONS="true",
        EXTENSIONS_RESULT="success",
    )
    assert _moved(calls)
    assert "Extension validation passed" in (tmp_path / "summary.md").read_text()


def test_failed_extension_validation_holds_v1(tmp_path):
    calls = _run(
        tmp_path,
        ACTION="canary",
        CANARY="true",
        CANARY_RESULT="success",
        EXTENSIONS="true",
        EXTENSIONS_RESULT="failure",
    )
    assert not _moved(calls)
    assert any(c.startswith("gh issue create") for c in calls)


def test_extensions_job_calls_the_validation_workflow_with_the_merge_commit():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    job = workflow["jobs"]["extensions"]
    assert job["uses"] == "./.github/workflows/extension-validation.yml"
    assert job["if"] == "needs.plan.outputs.extensions == 'true'"
    assert job["with"]["test_ref"] == "${{ needs.plan.outputs.sha }}"
    assert "extensions" in workflow["jobs"]["publish"]["needs"]
    called = yaml.safe_load((REPO_ROOT / ".github/workflows/extension-validation.yml").read_text())
    triggers = called[True] if True in called else called["on"]
    assert "workflow_call" in triggers
    assert set(triggers["workflow_call"]["inputs"]) >= {"profile", "test_ref"}
