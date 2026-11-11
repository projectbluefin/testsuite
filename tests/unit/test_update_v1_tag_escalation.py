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
