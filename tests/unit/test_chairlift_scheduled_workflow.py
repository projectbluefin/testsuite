"""The scheduled chairlift run (.github/workflows/chairlift-scheduled.yml, #1326).

Pins what it may and may not do: run the advisory suite once a day and on
dispatch, never on a fork or from a gate, and keep exactly one alert issue.
The alert script runs for real here against a fake ``gh`` on PATH.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "chairlift-scheduled.yml"
TITLE = "chairlift suite failing on dakota:testing"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as True.
    return workflow.get("on", workflow.get(True))


def test_runs_daily_and_on_dispatch_only(workflow):
    triggers = _triggers(workflow)
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert len(triggers["schedule"]) == 1
    assert workflow["permissions"] == {}


def test_boots_the_chairlift_suite_on_dakota_testing_through_e2e(workflow):
    suite = workflow["jobs"]["suite"]
    assert suite["uses"] == "./.github/workflows/e2e.yml"
    assert suite["with"]["suites"] == "chairlift"
    assert suite["with"]["image"] == "ghcr.io/projectbluefin/dakota:testing"
    assert suite["with"]["test_ref"] == "${{ github.sha }}"
    # The raw image whatever E2E_COMPOSE_IMAGE says.
    assert suite["with"]["compose_image"] is False
    assert suite["permissions"] == {"contents": "read", "packages": "write"}
    assert suite["if"] == "github.repository == 'projectbluefin/testsuite'"


def test_alert_runs_only_on_main_in_this_repository(workflow):
    alert = workflow["jobs"]["alert"]
    assert alert["needs"] == "suite"
    for guard in ("github.repository == 'projectbluefin/testsuite'", "github.ref == 'refs/heads/main'",
                  "!cancelled()"):
        assert guard in alert["if"]
    assert alert["permissions"] == {"actions": "read", "issues": "write"}
    assert alert["env"]["ALERT_TITLE"] == TITLE
    assert all("uses" not in step for step in alert["steps"])


def test_no_gate_or_other_workflow_calls_it():
    callers = [path.name for path in WORKFLOWS.glob("*.yml")
               if path != WORKFLOW and "chairlift-scheduled" in path.read_text()]
    assert callers == []


def test_every_external_action_is_pinned_by_sha():
    for line in WORKFLOW.read_text().splitlines():
        match = re.search(r"uses:\s*(\S+)", line)
        if match and not match.group(1).startswith("./"):
            assert re.search(r"@[0-9a-f]{40}\b", match.group(1)), line


# --- The alert script, run with a fake gh -----------------------------------

FAKE_GH = r"""#!/bin/bash
printf '%s\0' "$*" >> "$GH_LOG"  # one record per call; bodies span lines
case "$*" in
  "api --paginate --slurp repos/o/r/issues?"*) cat "$ISSUES_JSON" ;;
  "api --paginate --slurp repos/o/r/actions/runs/7/jobs?"*) cat "$JOBS_JSON" ;;
  "issue create "*) echo "https://github.com/o/r/issues/321" ;;
esac
"""


def _issue(number, title=TITLE, pull_request=False, user="github-actions[bot]"):
    issue = {"number": number, "title": title, "user": {"login": user}}
    if pull_request:
        issue["pull_request"] = {"url": "x"}
    return issue


JOBS = [[{"jobs": [
    {"name": "Run chairlift", "html_url": "https://x/job/1", "conclusion": "failure"},
    {"name": "Resolve test matrix", "html_url": "https://x/job/2", "conclusion": "success"},
]}]]


def _run_alert(workflow, tmp_path, result, issues):
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")  # always present on the hosted runner
    script = workflow["jobs"]["alert"]["steps"][0]["run"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    (tmp_path / "issues.json").write_text(json.dumps([issues]))
    (tmp_path / "jobs.json").write_text(json.dumps(JOBS[0]))
    log = tmp_path / "gh.log"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(log), "ISSUES_JSON": str(tmp_path / "issues.json"), "JOBS_JSON": str(tmp_path / "jobs.json"),
        "REPO": "o/r", "RESULT": result, "RUN_ID": "7", "RUN_URL": "https://x/run/7", "SHA": "abc123",
        "EVENT": "schedule", "ALERT_TITLE": TITLE,
    }
    proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    calls = log.read_text().split("\0")[:-1] if log.exists() else []
    writes = [call for call in calls if call.startswith("issue ")]
    return proc, writes, calls


def test_script_is_valid_bash(workflow):
    script = workflow["jobs"]["alert"]["steps"][0]["run"]
    subprocess.run(["bash", "-n", "-c", script], check=True)


def test_first_failure_opens_one_labelled_issue(workflow, tmp_path):
    proc, writes, _ = _run_alert(workflow, tmp_path, "failure", [_issue(5, "something else")])
    assert proc.returncode == 1
    creates = [w for w in writes if w.startswith("issue create")]
    assert len(creates) == 1 and f"--title {TITLE}" in creates[0]
    assert "Needs a maintainer:" in creates[0] and "gates nothing" in creates[0]
    assert "[Run chairlift](https://x/job/1) (failure)" in creates[0]
    assert "Resolve test matrix" not in creates[0]
    assert "issue edit 321 --add-label kind/bug" in writes
    assert "issue edit 321 --add-label needs-human" in writes
    assert "see #321" in proc.stdout


def test_a_later_failure_comments_and_never_opens_a_second_issue(workflow, tmp_path):
    issues = [_issue(40), _issue(12), _issue(9, pull_request=True)]
    proc, writes, _ = _run_alert(workflow, tmp_path, "failure", issues)
    assert proc.returncode == 1
    assert not any(w.startswith("issue create") for w in writes)
    comments = [w for w in writes if w.startswith("issue comment")]
    assert len(comments) == 1 and comments[0].startswith("issue comment 12 --body")


def test_a_pass_closes_the_open_issue_with_a_comment(workflow, tmp_path):
    proc, writes, _ = _run_alert(workflow, tmp_path, "success", [_issue(12)])
    assert proc.returncode == 0
    assert len(writes) == 1
    assert writes[0].startswith("issue close 12 --comment The chairlift suite passed on dakota:testing again")


def test_an_issue_someone_else_opened_with_the_title_is_left_alone(workflow, tmp_path):
    runs = [tmp_path / name for name in ("a", "b", "c")]
    for run in runs:
        run.mkdir()
    runs = iter(runs)
    proc, writes, _ = _run_alert(workflow, next(runs), "failure", [_issue(3, user="someone"), _issue(12)])
    assert proc.returncode == 1
    assert writes and all(w.split(" --")[0].split()[-1] == "12" for w in writes)
    assert not any(w.startswith("issue create") for w in writes)
    proc, writes, _ = _run_alert(workflow, next(runs), "success", [_issue(3, user="someone")])
    assert proc.returncode == 0 and writes == []
    proc, writes, _ = _run_alert(workflow, next(runs), "failure", [_issue(3, user="someone")])
    assert any(w.startswith("issue create") for w in writes)


def test_a_pass_with_no_issue_writes_nothing(workflow, tmp_path):
    proc, writes, calls = _run_alert(workflow, tmp_path, "success", [])
    assert proc.returncode == 0
    assert writes == []
    assert not any("actions/runs" in call for call in calls)
