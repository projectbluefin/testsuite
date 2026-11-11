"""Unit tests for filing the v1 gate's pre-existing failures (scripts/v1_gate_preexisting.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.v1_gate_compare import artifact_suffix
from scripts.v1_gate_preexisting import (
    MAX_ISSUES,
    TITLE_LIMIT,
    image_name,
    image_repo,
    issues,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "v1_gate_preexisting.py"
COMPARE = REPO_ROOT / "scripts" / "v1_gate_compare.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "update-v1-tag.yml"

DIGEST = "sha256:" + "ab" * 32
CANDIDATE = f"ghcr.io/projectbluefin/dakota:testing@{DIGEST}"
BASELINE = f"ghcr.io/projectbluefin/dakota@{DIGEST}"
RUN = "https://example.invalid/run/1"
POWER = "GNOME Settings panels :: Power settings panel is accessible"


def write_suite(root: Path, image: str, suite: str, conclusion: str, scenarios: dict):
    """Write e2e.yml's metadata and behave results for one suite job."""
    suffix = artifact_suffix(image)
    meta = root / f"e2e-metadata-{suffix}-{suite}"
    meta.mkdir(parents=True)
    (meta / "e2e-metadata.json").write_text(json.dumps({"conclusion": conclusion}))
    results = root / f"e2e-results-{suffix}-{suite}"
    results.mkdir(parents=True)
    features: dict[str, list] = {}
    for key, (status, location) in scenarios.items():
        feature, name = key.split(" :: ")
        features.setdefault(feature, []).append(
            {"type": "scenario", "name": name, "status": status, "location": location}
        )
    (results / "results.json").write_text(
        json.dumps([{"name": f, "elements": e} for f, e in features.items()])
    )


def test_image_name_and_repo():
    assert image_name(CANDIDATE) == "projectbluefin/dakota:testing"
    assert image_repo(CANDIDATE) == "projectbluefin/dakota"
    assert image_repo("quay.io/fedora/fedora-bootc:42") == ""


def test_one_issue_per_scenario_with_its_location(tmp_path):
    loc = "tests/smoke/features/gnome_settings.feature:55"
    write_suite(tmp_path, CANDIDATE, "smoke-b", "failure", {POWER: ("failed", loc)})
    out = issues(tmp_path, CANDIDATE, {"smoke-b": [POWER]}, RUN)
    assert len(out) == 1
    issue = out[0]
    assert issue["title"] == (
        f"e2e: smoke-b fails on projectbluefin/dakota:testing, also at v1: {POWER}"
    )
    assert issue["needs_human"] is False
    assert f"`{loc}`" in issue["body"]
    assert RUN in issue["body"]
    assert "`projectbluefin/dakota`" in issue["body"]
    assert "@quarantine" in issue["body"]


def test_location_is_relative_to_the_repo(tmp_path):
    # Real smoke-b output (run 43035684640) carries the guest checkout's name.
    write_suite(
        tmp_path,
        CANDIDATE,
        "smoke-b",
        "failure",
        {
            POWER: (
                "failed",
                "bluefin-tests/tests/smoke/features/gnome_settings.feature:55",
            )
        },
    )
    body = issues(tmp_path, CANDIDATE, {"smoke-b": [POWER]}, RUN)[0]["body"]
    assert "`tests/smoke/features/gnome_settings.feature:55`" in body
    assert "bluefin-tests/" not in body


def test_missing_results_still_files_without_a_location(tmp_path):
    out = issues(tmp_path, CANDIDATE, {"smoke-b": [POWER]}, RUN)
    assert len(out) == 1
    assert "search for the scenario name" in out[0]["body"]


def test_nothing_to_file():
    assert issues(Path("/nonexistent"), CANDIDATE, {}, RUN) == []
    assert issues(Path("/nonexistent"), CANDIDATE, {"smoke-b": []}, RUN) == []


def test_many_failures_become_one_issue_for_a_maintainer():
    many = {"smoke-a": [f"F :: s{i}" for i in range(MAX_ISSUES)], "common": ["F :: c"]}
    out = issues(Path("/nonexistent"), CANDIDATE, many, RUN)
    assert len(out) == 1
    assert out[0]["needs_human"] is True
    assert out[0]["title"] == (
        "e2e: many scenarios fail on projectbluefin/dakota:testing, also at v1"
    )
    assert "- `common`: F :: c" in out[0]["body"]
    assert f"{MAX_ISSUES + 1} scenarios fail" in out[0]["body"]
    # A later run with a different count must match the same open title.
    more = {"smoke-a": [f"F :: s{i}" for i in range(MAX_ISSUES + 4)]}
    assert (
        issues(Path("/nonexistent"), CANDIDATE, more, RUN)[0]["title"]
        == out[0]["title"]
    )


def test_exactly_the_limit_is_still_per_scenario():
    limit = {"smoke-a": [f"F :: s{i}" for i in range(MAX_ISSUES)]}
    out = issues(Path("/nonexistent"), CANDIDATE, limit, RUN)
    assert len(out) == MAX_ISSUES
    assert not any(i["needs_human"] for i in out)


def test_long_titles_are_cut_the_same_way_every_time():
    long = "F :: " + "x" * 400
    first = issues(Path("/nonexistent"), CANDIDATE, {"smoke-a": [long]}, RUN)[0][
        "title"
    ]
    again = issues(Path("/nonexistent"), CANDIDATE, {"smoke-a": [long]}, RUN)[0][
        "title"
    ]
    assert len(first) == TITLE_LIMIT
    assert first == again


def test_compare_writes_preexisting_and_the_cli_files_it(tmp_path):
    art = tmp_path / "artifacts"
    loc = "tests/smoke/features/gnome_settings.feature:55"
    write_suite(art, CANDIDATE, "smoke-b", "failure", {POWER: ("failed", loc)})
    write_suite(art, BASELINE, "smoke-b", "failure", {POWER: ("failed", loc)})
    pre = tmp_path / "preexisting.json"
    out = subprocess.run(
        [
            sys.executable,
            str(COMPARE),
            str(art),
            CANDIDATE,
            BASELINE,
            "--preexisting",
            str(pre),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "verdict=move" in out.stdout
    assert json.loads(pre.read_text()) == {"smoke-b": [POWER]}

    filed = subprocess.run(
        [sys.executable, str(SCRIPT), str(art), CANDIDATE, str(pre), RUN],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [json.loads(line) for line in filed.stdout.splitlines()]
    assert [line["title"] for line in lines] == [
        f"e2e: smoke-b fails on projectbluefin/dakota:testing, also at v1: {POWER}"
    ]
    assert f"`{loc}`" in lines[0]["body"]


def test_new_failures_are_not_preexisting(tmp_path):
    art = tmp_path / "artifacts"
    write_suite(art, CANDIDATE, "smoke-b", "failure", {POWER: ("failed", "a:1")})
    write_suite(art, BASELINE, "smoke-b", "success", {POWER: ("passed", "a:1")})
    pre = tmp_path / "preexisting.json"
    subprocess.run(
        [
            sys.executable,
            str(COMPARE),
            str(art),
            CANDIDATE,
            BASELINE,
            "--preexisting",
            str(pre),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(pre.read_text()) == {}


# The workflow step, run for real with a stubbed gh: it files each new title
# once, labels it, and skips titles that already have an open issue.
STUB_GH = """#!/bin/bash
echo "gh $*" >> "$GH_LOG"
case "$1 $2" in
  "issue list") printf '%s\\n' "$STUB_OPEN" ;;
  "issue create") echo "https://example.invalid/issues/$((1200 + $(grep -c 'issue create' "$GH_LOG")))" ;;
esac
exit 0
"""


def _step_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["publish"]["steps"]
    return next(
        s["run"] for s in steps if s.get("name") == "File pre-existing failures"
    )


def _run_step(tmp_path: Path, preexisting: dict, stub_open: str = "") -> list[str]:
    work = tmp_path / "work"
    (work / "scripts").mkdir(parents=True)
    for name in ("v1_gate_compare.py", "v1_gate_preexisting.py"):
        (work / "scripts" / name).write_text((REPO_ROOT / "scripts" / name).read_text())
    (work / "artifacts").mkdir()
    (work / "preexisting.json").write_text(json.dumps(preexisting))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    script = tmp_path / "step.sh"
    script.write_text(_step_script())
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "IMAGE": CANDIDATE,
        "RUN_URL": RUN,
        "STUB_OPEN": stub_open,
    }
    subprocess.run(
        ["bash", str(script)],
        cwd=work,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return log.read_text().splitlines()


def test_step_files_and_labels_a_new_failure(tmp_path):
    calls = _run_step(tmp_path, {"smoke-b": [POWER]})
    creates = [c for c in calls if c.startswith("gh issue create")]
    assert len(creates) == 1
    assert "--add-label kind/bug" in " ".join(calls)
    assert "--add-label triage/accepted" in " ".join(calls)
    assert "needs-human" not in " ".join(calls)
    assert "Pre-existing failures filed" in (tmp_path / "summary.md").read_text()


def test_step_skips_a_failure_that_already_has_an_open_issue(tmp_path):
    title = f"e2e: smoke-b fails on projectbluefin/dakota:testing, also at v1: {POWER}"
    calls = _run_step(
        tmp_path, {"smoke-b": [POWER]}, stub_open=f"Something else\n{title}"
    )
    assert not any(c.startswith("gh issue create") for c in calls)


def test_step_does_nothing_without_preexisting_failures(tmp_path):
    calls = _run_step(tmp_path, {})
    assert calls == []


def test_step_sends_many_failures_to_a_maintainer(tmp_path):
    many = {"smoke-a": [f"F :: s{i}" for i in range(MAX_ISSUES + 1)]}
    calls = _run_step(tmp_path, many)
    assert len([c for c in calls if c.startswith("gh issue create")]) == 1
    assert "--add-label needs-human" in " ".join(calls)
    assert "triage/accepted" not in " ".join(calls)
