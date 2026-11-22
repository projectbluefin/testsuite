"""Unit tests for the scheduled extension-validation attribution logic (scripts/extension_baseline.py).

Covers the three things the acceptance criteria call out: baseline selection,
the marker lookup, and the issue body. Also covers classify() and the CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.extension_baseline import (
    _create_issue,
    attribution_line,
    bot_issues,
    build_issue_body,
    classify,
    file_issues,
    find_existing_issue,
    main,
    marker,
    merge_rerun_outcomes,
    select_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "extension_baseline.py"

DIGEST = "sha256:" + "ab" * 32
CANDIDATE = {
    "profile": "just-perfection",
    "os_release": "nightly.20261117.0",
    "digest": "sha256:" + "cd" * 32,
    "shell_version": "48.0",
    "scenarios": ["test_a", "test_b"],
    "passed": False,
    "reason": "non-success scenarios present: test_a",
    "extension_zip": "extension-artifact/just-perfection.zip",
    "extension_sha256": DIGEST,
    "run_url": "https://github.com/projectbluefin/testsuite/actions/runs/1",
    "date": "2026-11-17",
}
BASELINE = {
    "profile": "just-perfection",
    "os_release": "nightly.20261110.0",
    "digest": "sha256:" + "12" * 32,
    "shell_version": "47.1",
    "passed": True,
    "run_url": "https://github.com/projectbluefin/testsuite/actions/runs/0",
    "date": "2026-11-10",
}
RERUN_PASSED = {"passed": True, "digest": BASELINE["digest"]}
RERUN_FAILED = {"passed": False, "digest": BASELINE["digest"]}


def _outcome(passed: bool, reason: str = "non-success scenarios present: test_a", infra: bool = False) -> dict:
    return {"passed": passed, "reason": reason, "infra": infra}


# --- classify ---------------------------------------------------------------

def test_classify_pass():
    assert classify(_outcome(True)) == "pass"


def test_classify_extension_failure():
    assert classify(_outcome(False, "non-success scenarios present: test_a")) == "extension"


def test_classify_infra_flag():
    assert classify(_outcome(False, "any", infra=True)) == "infrastructure"


def test_classify_infra_reason_string():
    assert classify(_outcome(False, "missing results for scenario")) == "infrastructure"
    assert classify(_outcome(False, "failed to boot the guest")) == "infrastructure"


# --- select_baseline --------------------------------------------------------

def test_select_baseline_returns_most_recent_passing():
    store = {"just-perfection": [BASELINE, {**CANDIDATE, "passed": True}]}
    assert select_baseline(store, "just-perfection")["os_release"] == "nightly.20261117.0"


def test_select_baseline_skips_failed_builds():
    store = {
        "just-perfection": [
            {**BASELINE, "passed": True},
            {"os_release": "nightly.20261115.0", "passed": False},
        ]
    }
    assert select_baseline(store, "just-perfection")["os_release"] == BASELINE["os_release"]


def test_select_baseline_empty_store_is_none():
    assert select_baseline({}, "just-perfection") is None


# --- marker / find_existing_issue -------------------------------------------

def test_marker_format():
    assert marker("sjc-gold") == "<!-- extension-validation: sjc-gold -->"


def test_find_existing_issue_matches_marker_and_bot():
    issues = [
        {"number": 1, "bot": True, "body": marker("sjc-gold") + " old failure"},
        {"number": 2, "bot": True, "body": "unrelated issue"},
    ]
    found = find_existing_issue(issues, "sjc-gold")
    assert found is not None and found["number"] == 1


def test_find_existing_issue_ignores_non_bot():
    issues = [{"number": 3, "bot": False, "body": marker("sjc-gold")}]
    assert find_existing_issue(issues, "sjc-gold") is None


def test_find_existing_issue_none_when_absent():
    assert find_existing_issue([], "sjc-gold") is None


# --- attribution_line / build_issue_body ------------------------------------

def test_attribution_no_baseline():
    line = attribution_line("just-perfection", CANDIDATE, None, None)
    assert "cannot yet be attributed" in line


def test_attribution_passes_on_baseline():
    line = attribution_line("just-perfection", CANDIDATE, BASELINE, RERUN_PASSED)
    assert "PASSES on" in line and "The change is in GNOME OS" in line


def test_attribution_fails_on_both():
    line = attribution_line("just-perfection", CANDIDATE, BASELINE, RERUN_FAILED)
    assert "FAILS on" in line and "Not a GNOME OS" in line


def test_attribution_infrastructure_is_inconclusive():
    infra = {**CANDIDATE, "classification": "infrastructure"}
    line = attribution_line("just-perfection", infra, BASELINE, RERUN_FAILED)
    assert "Inconclusive" in line


def test_attribution_infrastructure_rerun_is_inconclusive():
    rerun = {**RERUN_FAILED, "classification": "infrastructure"}
    line = attribution_line("just-perfection", CANDIDATE, BASELINE, rerun)
    assert "Inconclusive" in line


def test_build_issue_body_has_marker_and_sections():
    body = build_issue_body("just-perfection", CANDIDATE, BASELINE, RERUN_PASSED)
    assert marker("just-perfection") in body
    assert body.startswith("just-perfection failed")
    assert "## Attribution" in body and "## Candidate build" in body
    assert "## Baseline build" in body
    assert CANDIDATE["digest"][:19] in body
    assert CANDIDATE["digest"] in body  # full digest, not truncated
    assert CANDIDATE["run_url"] in body


def test_build_issue_body_no_baseline():
    body = build_issue_body("just-perfection", CANDIDATE, None, None)
    assert "## Baseline build" in body
    assert "cannot yet be attributed" in body


# --- CLI round-trips --------------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_cli_classify(tmp_path: Path):
    (tmp_path / "o.json").write_text(json.dumps(_outcome(False)))
    result = _run("classify", "--outcome", str(tmp_path / "o.json"))
    assert result.returncode == 0
    assert json.loads(result.stdout) == "extension"


def test_cli_select_baseline(tmp_path: Path):
    (tmp_path / "s.json").write_text(json.dumps({"just-perfection": [BASELINE]}))
    result = _run("select-baseline", "--store", str(tmp_path / "s.json"), "just-perfection")
    assert result.returncode == 0
    assert json.loads(result.stdout)["os_release"] == BASELINE["os_release"]


def test_cli_find_issue(tmp_path: Path):
    issues = [{"number": 5, "bot": True, "body": marker("sjc-gold")}]
    (tmp_path / "i.jsonl").write_text(json.dumps(issues[0]) + "\n")
    result = _run("find-issue", "--issues", str(tmp_path / "i.jsonl"), "sjc-gold")
    assert result.returncode == 0
    assert json.loads(result.stdout)["number"] == 5


def test_cli_body(tmp_path: Path):
    (tmp_path / "c.json").write_text(json.dumps(CANDIDATE))
    (tmp_path / "b.json").write_text(json.dumps(BASELINE))
    result = _run("body", "--profile", "just-perfection",
                  "--candidate", str(tmp_path / "c.json"),
                  "--baseline", str(tmp_path / "b.json"))
    assert result.returncode == 0
    assert marker("just-perfection") in result.stdout


# --- merge_rerun_outcomes / file_issues -------------------------------------

def test_merge_rerun_outcomes_attaches_rerun(tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection", "passed": False}}}
    out = tmp_path / "rerun-outcomes" / "just-perfection.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"profile": "just-perfection", "passed": True, "reason": "ok"}))
    merge_rerun_outcomes(report, str(tmp_path / "rerun-outcomes"))
    assert report["profiles"]["just-perfection"]["rerun"] == {
        "passed": True, "reason": "ok", "run_url": "", "classification": ""}


def test_merge_rerun_outcomes_missing_leaves_no_rerun(tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection"}}}
    merge_rerun_outcomes(report, str(tmp_path / "rerun-outcomes"))
    assert "rerun" not in report["profiles"]["just-perfection"]


def test_merge_rerun_outcomes_ignores_unknown_profile(tmp_path):
    report = {"profiles": {"known": {}}}
    out = tmp_path / "rerun-outcomes" / "other.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"profile": "other", "passed": True}))
    merge_rerun_outcomes(report, str(tmp_path / "rerun-outcomes"))
    assert "rerun" not in report["profiles"]["known"]


def test_merge_rerun_outcomes_copies_classification(tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection", "passed": False}}}
    out = tmp_path / "rerun-outcomes" / "just-perfection.json"
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"profile": "just-perfection", "passed": False,
                               "reason": "infra", "classification": "infrastructure"}))
    merge_rerun_outcomes(report, str(tmp_path / "rerun-outcomes"))
    assert report["profiles"]["just-perfection"]["rerun"]["classification"] == "infrastructure"


def test_bot_issues_flags_bot_authors(monkeypatch):
    import types
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            stdout=json.dumps([{"number": 7, "author": {"login": "github-actions[bot]",
                                "is_bot": True}, "title": "x", "body": ""}]))

    monkeypatch.setattr("scripts.extension_baseline.subprocess.run", fake_run)
    issues = bot_issues("tok")
    assert [i["number"] for i in issues] == [7]
    assert "author" in " ".join(captured["cmd"])


def test_file_issues_creates_when_absent(monkeypatch, tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection",
                                               "digest": "sha256:aa", "baseline": None,
                                               "rerun": None, "os_release": "x"}}}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    monkeypatch.setattr("scripts.extension_baseline.bot_issues", lambda token: [])
    monkeypatch.setattr("scripts.extension_baseline._create_issue",
                        lambda token, profile, body: 11)
    created = {"profile": None, "body": None}

    def fake_create(token, profile, body):
        created["profile"] = profile
        created["body"] = body
        return 11

    monkeypatch.setattr("scripts.extension_baseline._create_issue", fake_create)
    assert file_issues(str(report_path), "tok") == 1
    assert created["profile"] == "just-perfection"
    assert marker("just-perfection") in created["body"]


def test_file_issues_edits_existing(monkeypatch, tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection",
                                               "digest": "sha256:aa", "baseline": None,
                                               "rerun": None, "os_release": "x"}}}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    monkeypatch.setattr("scripts.extension_baseline.bot_issues",
                        lambda token: [{"number": 42, "author": {"bot": True},
                                        "bot": True, "body": marker("just-perfection")}])
    edited = {"number": None}
    monkeypatch.setattr("scripts.extension_baseline._edit_issue",
                        lambda token, number, body: edited.__setitem__("number", number))
    assert file_issues(str(report_path), "tok") == 1
    assert edited["number"] == 42


def test_file_issues_requires_token(monkeypatch, tmp_path):
    report = {"profiles": {}}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    assert file_issues(str(report_path), "") == 1


def test_cli_file_issues(monkeypatch, tmp_path):
    report = {"profiles": {"just-perfection": {"profile": "just-perfection",
                                               "digest": "sha256:aa", "baseline": None,
                                               "rerun": None, "os_release": "x"}}}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    monkeypatch.setattr("scripts.extension_baseline.bot_issues", lambda token: [])
    monkeypatch.setattr("scripts.extension_baseline._create_issue",
                        lambda token, profile, body: 3)
    monkeypatch.setenv("GH_TOKEN", "tok")
    rc = main(["file-issues", "--report", str(report_path)])
    assert rc == 0


def test_create_issue_parses_issue_url(monkeypatch):
    import types
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            stdout="Issue created. URL: https://github.com/projectbluefin/testsuite/issues/123\n",
            stderr="")

    monkeypatch.setattr("scripts.extension_baseline.subprocess.run", fake_run)
    number = _create_issue("tok", "sjc-gold", "body")
    assert number == 123
    assert "issue create" in " ".join(captured["cmd"])
