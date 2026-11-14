"""Unit tests for scripts/quarantine_followup.py with GitHub mocked."""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import quarantine_followup as qf

CITE = "# quarantine: projectbluefin/dakota#1875 extension missing on dakota:testing"
CLOSED_ISSUE = {
    "data": {
        "repository": {
            "issueOrPullRequest": {
                "__typename": "Issue",
                "title": "power-status-color missing",
                "url": "https://github.com/projectbluefin/dakota/issues/1875",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-11-11T18:28:10Z",
                "timelineItems": {
                    "nodes": [
                        {
                            "closer": {
                                "__typename": "PullRequest",
                                "number": 1876,
                                "url": "https://github.com/projectbluefin/dakota/pull/1876",
                                "merged": True,
                                "repository": {"nameWithOwner": "projectbluefin/dakota"},
                            }
                        }
                    ]
                },
            }
        }
    }
}
OPEN_ISSUE = {
    "data": {
        "repository": {
            "issueOrPullRequest": {
                "__typename": "Issue",
                "title": "still broken",
                "url": "https://github.com/projectbluefin/utah/issues/5",
                "state": "OPEN",
                "stateReason": None,
                "closedAt": None,
                "timelineItems": {"nodes": []},
            }
        }
    }
}


class FakeGitHub:
    def __init__(self, statuses: dict[str, dict], issues: list[dict] | None = None):
        self.statuses = statuses
        self.issues = issues or []
        self.writes: list[tuple] = []

    def citation_status(self, repo, number):
        ref = f"{repo}#{number}"
        return qf.parse_status(ref, self.statuses.get(ref, {"data": {"repository": None}}))

    def open_issues(self, repo):
        return list(self.issues)

    def create_issue(self, repo, title, body, labels):
        self.writes.append(("create", title, labels))
        return 999

    def update_issue(self, repo, number, **fields):
        self.writes.append(("update", number, fields))

    def comment(self, repo, number, body):
        self.writes.append(("comment", number, body))


def _git(root: Path, *args: str, when: str | None = None) -> None:
    env = None
    if when:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


def _repo(tmp_path: Path, features: dict[str, str], when: str = "2026-11-11T12:00:00+00:00") -> Path:
    _git(tmp_path, "init", "-q")
    for rel, text in features.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init", when=when)
    return tmp_path


def _feature(cite: str, scenarios: int = 1) -> str:
    body = "Feature: Example\n"
    for n in range(scenarios):
        body += f"\n  {cite}\n  @smoke @quarantine\n  Scenario: S{n}\n    * a step\n"
    return body


def _args(root: Path, today: date, **extra) -> SimpleNamespace:
    values = dict(
        repo="projectbluefin/testsuite",
        sha="a" * 40,
        repo_root=root,
        max_days=30,
        grace_days=0,
        warn_days=7,
        today=today,
        dry_run=True,
        no_bodies=False,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def test_parse_status_closed_issue_names_its_closing_pr():
    status = qf.parse_status("projectbluefin/dakota#1875", CLOSED_ISSUE)
    assert status.closed is True
    assert status.kind == "issue"
    assert status.how == "completed"
    assert status.closed_by == "projectbluefin/dakota#1876 (merged)"
    assert status.closed_at == datetime(2026, 11, 11, 18, 28, 10, tzinfo=timezone.utc)
    assert qf.eastern(status.closed_at) == "2026-11-11 13:28 EST"


def test_parse_status_open_issue_and_missing():
    assert qf.parse_status("projectbluefin/utah#5", OPEN_ISSUE).closed is False
    missing = qf.parse_status("projectbluefin/utah#9", {"data": {"repository": None}})
    assert missing.kind == "missing"


def test_parse_status_pull_request_merged_and_unmerged():
    merged = {
        "data": {
            "repository": {
                "issueOrPullRequest": {
                    "__typename": "PullRequest",
                    "title": "fix",
                    "url": "u",
                    "state": "MERGED",
                    "merged": True,
                    "mergedAt": "2026-11-01T00:00:00Z",
                    "closedAt": "2026-11-01T00:00:00Z",
                }
            }
        }
    }
    status = qf.parse_status("projectbluefin/dakota#1", merged)
    assert (status.kind, status.closed, status.how) == ("pull", True, "merged")
    unmerged = json.loads(json.dumps(merged))
    node = unmerged["data"]["repository"]["issueOrPullRequest"]
    node.update(state="CLOSED", merged=False, mergedAt=None)
    assert qf.parse_status("projectbluefin/dakota#1", unmerged).how == "closed without merging"


def test_closed_citation_proposes_one_lift_issue(tmp_path):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE, scenarios=2)})
    github = FakeGitHub({"projectbluefin/dakota#1875": CLOSED_ISSUE})
    plan, cited = qf.run(_args(root, date(2026, 11, 14)), github)
    assert cited == ["projectbluefin/dakota#1875"] * 2
    assert [a.kind for a in plan.actions] == ["create"]
    action = plan.actions[0]
    assert action.key == "lift projectbluefin/dakota#1875"
    assert action.labels == qf.LIFT_LABELS
    assert "switch 2 skipped tests back on" in action.title
    body = action.body
    assert body.startswith("<!-- quarantine-followup: lift projectbluefin/dakota#1875 -->")
    assert "**Summary:**" in body
    assert "tests/smoke/features/a.feature:4" in body
    assert f"blob/{'a' * 40}/tests/smoke/features/a.feature#L4" in body
    assert "projectbluefin/dakota#1876 (merged)" in body
    assert "2026-11-11 13:28 EST" in body
    assert "ghcr.io/projectbluefin/dakota:testing" in body
    assert "No manual run is needed" in body
    assert "## Acceptance criteria" in body and "## Test plan" in body
    assert github.writes == []


def test_open_citation_young_quarantine_needs_nothing(tmp_path):
    cite = "# quarantine: projectbluefin/utah#5 broken on utah"
    root = _repo(tmp_path, {"tests/common/features/a.feature": _feature(cite)})
    github = FakeGitHub({"projectbluefin/utah#5": OPEN_ISSUE})
    plan, _ = qf.run(_args(root, date(2026, 11, 14)), github)
    assert plan.actions == []
    assert any("projectbluefin/utah#5: open" in note for note in plan.notes)


def test_open_citation_near_limit_warns(tmp_path):
    cite = "# quarantine: projectbluefin/utah#5 broken on utah"
    root = _repo(
        tmp_path,
        {"tests/common/features/a.feature": _feature(cite)},
        when="2026-10-20T12:00:00+00:00",
    )
    github = FakeGitHub({"projectbluefin/utah#5": OPEN_ISSUE})
    # 2026-10-20 + 23 days = 2026-11-12: exactly 7 days before the 30-day limit.
    plan, _ = qf.run(_args(root, date(2026, 11, 12)), github)
    assert [a.kind for a in plan.actions] == ["create"]
    action = plan.actions[0]
    assert action.key == "expiring projectbluefin/utah#5"
    assert action.labels == qf.EXPIRING_LABELS
    assert "2026-11-20" in action.title  # first failing day: age 31
    assert "will start failing" in action.body

    one_day_earlier, _ = qf.run(_args(root, date(2026, 11, 11)), github)
    assert one_day_earlier.actions == []


def test_grace_days_move_the_warning(tmp_path):
    cite = "# quarantine: projectbluefin/utah#5 broken on utah"
    root = _repo(
        tmp_path,
        {"tests/common/features/a.feature": _feature(cite)},
        when="2026-10-20T12:00:00+00:00",
    )
    github = FakeGitHub({"projectbluefin/utah#5": OPEN_ISSUE})
    plan, _ = qf.run(_args(root, date(2026, 11, 12), grace_days=30), github)
    assert plan.actions == []


def test_expired_open_citation_says_it_is_failing(tmp_path):
    cite = "# quarantine: projectbluefin/utah#5 broken on utah"
    root = _repo(
        tmp_path,
        {"tests/common/features/a.feature": _feature(cite)},
        when="2026-09-01T12:00:00+00:00",
    )
    github = FakeGitHub({"projectbluefin/utah#5": OPEN_ISSUE})
    plan, _ = qf.run(_args(root, date(2026, 11, 12)), github)
    assert "has been failing pull request checks since 2026-10-02" in plan.actions[0].body


def test_utah_lift_asks_for_a_manual_utah_run(tmp_path):
    cite = "# quarantine: projectbluefin/utah#5 broken on utah"
    root = _repo(tmp_path, {"tests/common/features/a.feature": _feature(cite)})
    closed = json.loads(json.dumps(CLOSED_ISSUE))
    github = FakeGitHub({"projectbluefin/utah#5": closed})
    plan, _ = qf.run(_args(root, date(2026, 11, 14)), github)
    body = plan.actions[0].body
    assert "ghcr.io/projectbluefin/utah:testing" in body
    assert "Manual Test Run" in body and "suites `common`" in body


def _existing(plan_action: qf.Action, number: int, **overrides) -> dict:
    issue = {"number": number, "title": plan_action.title, "body": plan_action.body}
    issue.update(overrides)
    return issue


def test_existing_issue_is_kept_not_duplicated(tmp_path):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    statuses = {"projectbluefin/dakota#1875": CLOSED_ISSUE}
    first, _ = qf.run(_args(root, date(2026, 11, 14)), FakeGitHub(statuses))
    issue = _existing(first.actions[0], 50)

    again, _ = qf.run(_args(root, date(2026, 11, 20)), FakeGitHub(statuses, [issue]))
    assert [(a.kind, a.number) for a in again.actions] == [("keep", 50)]


def test_new_sha_alone_is_not_an_edit(tmp_path):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    statuses = {"projectbluefin/dakota#1875": CLOSED_ISSUE}
    first, _ = qf.run(_args(root, date(2026, 11, 14)), FakeGitHub(statuses))
    issue = _existing(first.actions[0], 50)
    moved, _ = qf.run(
        _args(root, date(2026, 11, 14), sha="b" * 40), FakeGitHub(statuses, [issue])
    )
    assert [a.kind for a in moved.actions] == ["keep"]


def test_changed_content_updates_in_place_and_closes_duplicates(tmp_path):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    statuses = {"projectbluefin/dakota#1875": CLOSED_ISSUE}
    first, _ = qf.run(_args(root, date(2026, 11, 14)), FakeGitHub(statuses))
    stale = _existing(first.actions[0], 50, body=first.actions[0].body.replace("a.feature:4", "a.feature:9"))
    duplicate = _existing(first.actions[0], 61)
    github = FakeGitHub(statuses, [duplicate, stale])
    plan, _ = qf.run(_args(root, date(2026, 11, 14), dry_run=False), github)
    assert [(a.kind, a.number) for a in plan.actions] == [("update", 50), ("close", 61)]
    assert "Duplicate of #50" in plan.actions[1].comment

    qf.apply_plan(plan, github, "projectbluefin/testsuite")
    kinds = [w[0] for w in github.writes]
    assert kinds == ["update", "comment", "update"]
    assert github.writes[2][2] == {"state": "closed", "state_reason": "not_planned"}


def test_followup_for_lifted_quarantine_is_closed(tmp_path):
    root = _repo(
        tmp_path,
        {"tests/smoke/features/a.feature": "Feature: A\n\n  Scenario: S\n    * a step\n"},
    )
    leftover = {
        "number": 70,
        "title": "old",
        "body": "<!-- quarantine-followup: lift projectbluefin/dakota#1875 -->\nold",
    }
    unrelated = {"number": 71, "title": "x", "body": "no marker"}
    github = FakeGitHub({}, [leftover, unrelated])
    plan, _ = qf.run(_args(root, date(2026, 11, 14)), github)
    assert [(a.kind, a.number, a.reason) for a in plan.actions] == [("close", 70, "completed")]


def test_expiring_issue_closes_when_the_cause_closes(tmp_path):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    warning = {
        "number": 80,
        "title": "old",
        "body": "<!-- quarantine-followup: expiring projectbluefin/dakota#1875 -->",
    }
    github = FakeGitHub({"projectbluefin/dakota#1875": CLOSED_ISSUE}, [warning])
    plan, _ = qf.run(_args(root, date(2026, 11, 14)), github)
    assert [(a.kind, a.key, a.number) for a in plan.actions] == [
        ("create", "lift projectbluefin/dakota#1875", None),
        ("close", "expiring projectbluefin/dakota#1875", 80),
    ]


def test_missing_citation_and_invalid_tags_become_notes(tmp_path):
    root = _repo(
        tmp_path,
        {
            "tests/smoke/features/a.feature": _feature(
                "# quarantine: projectbluefin/dakota#4040 typo in number"
            ),
            "tests/smoke/features/b.feature": "Feature: B\n\n  @quarantine\n  Scenario: S\n",
        },
    )
    plan, cited = qf.run(_args(root, date(2026, 11, 14)), FakeGitHub({}))
    assert plan.actions == []
    assert cited == ["projectbluefin/dakota#4040"]
    assert any("not found on GitHub" in note for note in plan.notes)
    assert any("b.feature:3" in note for note in plan.notes)


def test_dry_run_prints_and_writes_nothing(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    github = FakeGitHub({"projectbluefin/dakota#1875": CLOSED_ISSUE})
    monkeypatch.setattr(qf, "GitHub", lambda: github)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rc = qf.main(
        ["--dry-run", "--repo-root", str(root), "--sha", "c" * 40, "--today", "2026-11-14"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "CREATE new issue [lift projectbluefin/dakota#1875]" in out
    assert "| <!-- quarantine-followup: lift projectbluefin/dakota#1875 -->" in out
    assert github.writes == []


def test_live_run_writes_and_records_step_summary(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path, {"tests/smoke/features/a.feature": _feature(CITE)})
    github = FakeGitHub({"projectbluefin/dakota#1875": CLOSED_ISSUE})
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(qf, "GitHub", lambda: github)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert qf.main(["--repo-root", str(root), "--sha", "c" * 40, "--today", "2026-11-14"]) == 0
    assert github.writes[0][0] == "create"
    assert github.writes[0][2] == qf.LIFT_LABELS
    assert "created #999" in summary.read_text()


def test_gh_client_builds_expected_commands():
    calls = []

    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs.get("input")))
        if cmd[2] == "graphql":
            out = json.dumps(OPEN_ISSUE)
        elif "--paginate" in cmd:
            out = '{"number": 1, "title": "t", "body": "b", "labels": []}\n'
        else:
            out = '{"number": 12}'
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    gh = qf.GitHub(runner)
    assert gh.citation_status("projectbluefin/utah", 5).closed is False
    assert calls[0][0][:3] == ["gh", "api", "graphql"]
    assert "number=5" in calls[0][0] and "owner=projectbluefin" in calls[0][0]
    assert gh.open_issues("projectbluefin/testsuite")[0]["number"] == 1
    assert gh.create_issue("projectbluefin/testsuite", "t", "b", ("kind/cleanup",)) == 12
    assert json.loads(calls[-1][1]) == {"title": "t", "body": "b", "labels": ["kind/cleanup"]}


def test_gh_failure_raises():
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 403")

    with pytest.raises(RuntimeError, match="HTTP 403"):
        qf.GitHub(runner).open_issues("projectbluefin/testsuite")
