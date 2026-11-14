#!/usr/bin/env python3
"""Open follow-up issues so @quarantine scenarios do not outlive their cause.

Reads every ``# quarantine: projectbluefin/<repo>#<N> <reason>`` citation (see
scripts/quarantine_citations.py), asks GitHub whether each cited issue or pull
request is closed, and keeps one open testsuite issue per citation that needs
a person or an agent:

- ``lift``: the citation is closed, so the quarantines that cite it can be
  lifted. The issue lists every file:line at the current commit, the closing
  date and closing PR, the image to verify on, acceptance criteria and a test
  plan, so a contributor agent can act on it cold.
- ``expiring``: the citation is still open and a quarantine that cites it is
  within ``--warn-days`` of the age limit scripts/check_quarantine_age.py
  enforces, or past it. Somebody has to decide what happens next.

Each issue carries a hidden ``<!-- quarantine-followup: <kind> <citation> -->``
marker. Later runs update that issue in place rather than filing another, close
duplicates, and close a follow-up whose quarantines are gone or whose kind no
longer applies. Labels are set only when an issue is created.

GitHub is reached through the ``gh`` CLI (``GH_TOKEN`` in Actions).
``--dry-run`` performs the reads and prints every write it would make.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_quarantine_age import (  # noqa: E402
    QUARANTINE_MAX_DAYS,
    build_quarantine_entries,
    find_quarantined_scenarios,
)
from quarantine_citations import QuarantineBlock, scan  # noqa: E402

MARKER_PREFIX = "quarantine-followup:"
MARKER_RE = re.compile(r"<!--\s*quarantine-followup:\s*(?P<key>[^>]+?)\s*-->")
WARN_DAYS = 7
EASTERN = ZoneInfo("America/New_York")

# Labels set when an issue is created. A lift is mechanical, agent-ready work;
# an expiring quarantine needs a maintainer's call (fix the cause, reclassify
# it, or delete it), so it goes to the human queue.
LIFT_LABELS = ("kind/cleanup", "triage/accepted")
EXPIRING_LABELS = ("kind/cleanup", "needs-human")

# Images a citation's repository implies. The PR VM check boots dakota:testing
# by digest, so a dakota citation is proven by that check alone.
CITATION_IMAGES = {
    "dakota": "ghcr.io/projectbluefin/dakota:testing",
    "utah": "ghcr.io/projectbluefin/utah:testing",
}
PR_VM_CHECK_IMAGE = "ghcr.io/projectbluefin/dakota:testing"

STATUS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        title url state stateReason closedAt
        timelineItems(itemTypes: [CLOSED_EVENT], last: 1) {
          nodes {
            ... on ClosedEvent {
              closer {
                __typename
                ... on PullRequest { number url merged repository { nameWithOwner } }
                ... on Commit { oid url }
              }
            }
          }
        }
      }
      ... on PullRequest { title url state closedAt merged mergedAt }
    }
  }
}
"""


@dataclass(frozen=True)
class CitationStatus:
    ref: str
    kind: str  # issue, pull or missing
    title: str = ""
    url: str = ""
    closed: bool = False
    closed_at: datetime | None = None
    how: str = ""  # completed, not planned, merged, closed without merging
    closed_by: str = ""  # "projectbluefin/dakota#1876 (merged)" or a commit


@dataclass
class Item:
    """One quarantine block joined with its age."""

    block: QuarantineBlock
    quarantined_on: date | None
    age_days: int | None


@dataclass
class Followup:
    key: str
    title: str
    body: str
    labels: tuple[str, ...]


@dataclass
class Action:
    kind: str  # create, update, close, keep
    key: str
    number: int | None = None
    title: str = ""
    body: str = ""
    labels: tuple[str, ...] = ()
    comment: str = ""
    reason: str = ""  # close state_reason


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


Runner = Callable[..., subprocess.CompletedProcess]


class GitHub:
    """The few GitHub calls this script makes, through ``gh api``."""

    def __init__(self, runner: Runner = subprocess.run):
        self._run = runner

    def _gh(self, args: list[str], payload: dict | None = None) -> str:
        result = self._run(
            ["gh", "api", *args],
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"gh api {' '.join(args[:3])} failed: {result.stderr.strip()}"
            )
        return result.stdout

    def citation_status(self, repo: str, number: int) -> CitationStatus:
        owner, name = repo.split("/", 1)
        out = self._gh(
            [
                "graphql",
                "-f",
                f"query={STATUS_QUERY}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={number}",
            ]
        )
        return parse_status(f"{repo}#{number}", json.loads(out))

    def open_issues(self, repo: str) -> list[dict[str, Any]]:
        out = self._gh(
            [
                f"repos/{repo}/issues?state=open&per_page=100",
                "--paginate",
                "--jq",
                ".[] | select(.pull_request == null) "
                "| {number, title, body, labels: [.labels[].name]}",
            ]
        )
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def create_issue(self, repo: str, title: str, body: str, labels: tuple[str, ...]) -> int:
        out = self._gh(
            ["-X", "POST", f"repos/{repo}/issues", "--input", "-"],
            {"title": title, "body": body, "labels": list(labels)},
        )
        return int(json.loads(out)["number"])

    def update_issue(self, repo: str, number: int, **fields: Any) -> None:
        self._gh(["-X", "PATCH", f"repos/{repo}/issues/{number}", "--input", "-"], fields)

    def comment(self, repo: str, number: int, body: str) -> None:
        self._gh(
            ["-X", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-"],
            {"body": body},
        )


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def parse_status(ref: str, payload: dict[str, Any]) -> CitationStatus:
    node = (
        ((payload.get("data") or {}).get("repository") or {}).get("issueOrPullRequest")
    )
    if not node:
        return CitationStatus(ref=ref, kind="missing")
    if node["__typename"] == "PullRequest":
        merged = bool(node.get("merged"))
        closed = node.get("state") in ("CLOSED", "MERGED")
        return CitationStatus(
            ref=ref,
            kind="pull",
            title=node.get("title", ""),
            url=node.get("url", ""),
            closed=closed,
            closed_at=_parse_time(node.get("mergedAt") or node.get("closedAt")),
            how=("merged" if merged else "closed without merging") if closed else "",
        )
    closed = node.get("state") == "CLOSED"
    closed_by = ""
    nodes = ((node.get("timelineItems") or {}).get("nodes")) or []
    closer = (nodes[-1] or {}).get("closer") if nodes else None
    if closed and closer:
        if closer.get("__typename") == "PullRequest":
            merged = " (merged)" if closer.get("merged") else ""
            closed_by = (
                f"{closer['repository']['nameWithOwner']}#{closer['number']}{merged}"
            )
        elif closer.get("__typename") == "Commit":
            closed_by = f"commit {closer['oid'][:12]} ({closer.get('url', '')})"
    reason = (node.get("stateReason") or "").lower().replace("_", " ")
    return CitationStatus(
        ref=ref,
        kind="issue",
        title=node.get("title", ""),
        url=node.get("url", ""),
        closed=closed,
        closed_at=_parse_time(node.get("closedAt")),
        how=reason if closed else "",
        closed_by=closed_by,
    )


def collect_items(repo_root: Path, today: date) -> tuple[list[Item], list[str]]:
    """Every cited quarantine block with its age, plus problem lines."""
    blocks, problems = scan(repo_root)
    entries = build_quarantine_entries(
        find_quarantined_scenarios(repo_root),
        today=today,
        max_days=0,
        grace_days=0,
        repo_root=repo_root,
    )
    by_scenario = {(str(e.feature_file), e.scenario_name): e for e in entries}
    items: list[Item] = []
    for block in blocks:
        if block.citation is None:
            continue
        ages = [
            by_scenario[(str(block.feature_file), name)]
            for name in block.scenarios
            if (str(block.feature_file), name) in by_scenario
        ]
        oldest = max(ages, key=lambda e: e.age_days) if ages else None
        items.append(
            Item(
                block=block,
                quarantined_on=oldest.quarantined_on if oldest else None,
                age_days=oldest.age_days if oldest else None,
            )
        )
    return items, [p.format() for p in problems]


def eastern(moment: datetime | None) -> str:
    if moment is None:
        return "unknown time"
    local = moment.astimezone(EASTERN)
    return local.strftime("%Y-%m-%d %H:%M ") + (local.tzname() or "ET")


def _suite(item: Item) -> str:
    parts = item.block.feature_file.parts
    return parts[1] if len(parts) > 1 and parts[0] == "tests" else "?"


def _rows(items: list[Item], repo: str, sha: str) -> list[str]:
    rows = []
    for item in sorted(items, key=lambda i: (str(i.block.feature_file), i.block.tag_line)):
        block = item.block
        anchor = f"{block.feature_file}:{block.tag_line}"
        link = f"https://github.com/{repo}/blob/{sha}/{block.feature_file}#L{block.tag_line}"
        names = "<br>".join(block.scenarios) or block.name
        since = item.quarantined_on.isoformat() if item.quarantined_on else "unknown"
        rows.append(f"| [`{anchor}`]({link}) | {block.level} | {names} | {since} |")
    return rows


def _scenario_count(items: list[Item]) -> int:
    return len({(str(i.block.feature_file), s) for i in items for s in i.block.scenarios})


def _verify_section(citation_repo: str, suites: list[str]) -> list[str]:
    image = CITATION_IMAGES.get(citation_repo)
    suite_list = ",".join(suites)
    if image == PR_VM_CHECK_IMAGE:
        return [
            f"The citation is in `projectbluefin/{citation_repo}`, so verify on "
            f"`{image}`. The **PR VM check** boots exactly that image (pinned by "
            f"digest) for the suites a PR touches (`{suite_list}`), so its result "
            "on your PR is the evidence. No manual run is needed.",
        ]
    if image:
        return [
            f"The citation is in `projectbluefin/{citation_repo}`, so verify on "
            f"`{image}`. The PR VM check only boots `{PR_VM_CHECK_IMAGE}`, which "
            "does not prove this. Ask a maintainer to run **Manual Test Run** "
            f"(`manual.yml`) with image `{image}`, suites `{suite_list}` and "
            "`test_ref` set to the PR's head commit, and link the run in the PR. "
            "Contributor agents cannot dispatch workflows.",
        ]
    return [
        f"The citation (`projectbluefin/{citation_repo}`) does not imply one "
        f"image. The PR VM check's run on `{PR_VM_CHECK_IMAGE}` for suites "
        f"`{suite_list}` is the evidence.",
    ]


def lift_followup(
    status: CitationStatus, items: list[Item], *, repo: str, sha: str
) -> Followup:
    citation = items[0].block.citation
    assert citation is not None
    count = _scenario_count(items)
    tests = "test" if count == 1 else "tests"
    suites = sorted({_suite(i) for i in items})
    closed_line = f"Closed {eastern(status.closed_at)}"
    if status.how:
        closed_line += f" as {status.how}"
    if status.closed_by:
        closed_line += f", by {status.closed_by}"
    unfixed = status.how in ("not planned", "closed without merging", "duplicate")
    summary = (
        f"{count} automated {tests} in this repository are switched off "
        f"(\"quarantined\") because of a problem tracked in {citation.ref}. That "
        "issue is now closed, so the tests can probably be switched back on, "
        "which restores the checking they do on every image build."
    )
    if unfixed:
        summary += (
            " It was closed without a fix, so the tests may still fail; the "
            "steps below cover that case."
        )
    lines = [
        f"<!-- {MARKER_PREFIX} lift {citation.ref} -->",
        f"**Summary:** {summary}",
        "",
        "---",
        "",
        "## The cause is closed",
        "",
        f"- Citation: [{citation.ref}]({status.url}) — {status.title}",
        f"- {closed_line}",
        f"- Reason given in the feature files: {citation.reason}",
        "",
        f"## Quarantines to lift (at `{sha[:12]}`)",
        "",
        "| Tag line | Level | Scenario(s) | Quarantined since |",
        "|---|---|---|---|",
        *_rows(items, repo, sha),
        "",
        "## What to do",
        "",
        "1. In each file above, delete `@quarantine` from the tag line and delete "
        f"the `# quarantine: {citation.ref} ...` line directly above it. Keep every "
        "other tag and comment.",
        "2. Run `python3 scripts/update_coverage_snapshot.py`; it regenerates the "
        "quarantine counts in `docs/skills/test-authoring/suite-map/SKILL.md`.",
        "3. Open a PR whose body says `Fixes #<this issue>`. Do not dispatch "
        "workflows; the PR's own checks are the proof.",
        "4. If the VM check shows a lifted scenario still failing, do not restore "
        f"the {citation.ref} citation. Either fix the scenario, or re-quarantine it "
        "with a citation to an open issue that describes the remaining failure "
        "(file one in the image's repository if needed).",
        "",
        "## Images to verify on",
        "",
        *_verify_section(citation.repo_name, suites),
        "",
        "## Acceptance criteria",
        "",
        f"- [ ] No `# quarantine: {citation.ref}` line remains under `tests/`, and the "
        "tags it annotated no longer carry `@quarantine`.",
        "- [ ] `python3 scripts/quarantine_citations.py` and "
        "`python3 scripts/update_coverage_snapshot.py --check` pass.",
        f"- [ ] The PR VM check is green for `{','.join(suites)}`, with the lifted "
        "scenarios reported as passed rather than skipped.",
        "",
        "## Test plan",
        "",
        "```",
        f"grep -rn '# quarantine: {citation.ref}' tests/   # expect no output",
        "python3 scripts/quarantine_citations.py",
        "python3 scripts/update_coverage_snapshot.py --check",
        "python3 scripts/check_quarantine_age.py --grace-days 30",
        "```",
        "",
        "Then read the PR VM check's behave summary for each scenario listed above.",
        "",
        "## Out of scope",
        "",
        "- Quarantines that cite anything else.",
        "- Changing the scenarios' steps, unless the VM check shows they need it.",
        "",
        "_Kept up to date by `.github/workflows/quarantine-followup.yml` "
        "(`scripts/quarantine_followup.py`). It closes this issue once the "
        "quarantines are gone._",
    ]
    return Followup(
        key=f"lift {citation.ref}",
        title=(
            f"test: switch {count} skipped {tests} back on now that "
            f"{citation.ref} is closed"
        ),
        body="\n".join(lines) + "\n",
        labels=LIFT_LABELS,
    )


def expiring_followup(
    status: CitationStatus,
    items: list[Item],
    *,
    repo: str,
    sha: str,
    threshold_days: int,
) -> Followup:
    citation = items[0].block.citation
    assert citation is not None
    count = _scenario_count(items)
    tests = "test" if count == 1 else "tests"
    oldest = max(
        (i for i in items if i.quarantined_on is not None),
        key=lambda i: i.age_days or 0,
    )
    assert oldest.quarantined_on is not None
    fails_on = oldest.quarantined_on + timedelta(days=threshold_days + 1)
    expired = (oldest.age_days or 0) > threshold_days
    when = (
        f"has been failing pull request checks since {fails_on.isoformat()}"
        if expired
        else f"will start failing every pull request's checks on {fails_on.isoformat()}"
    )
    lines = [
        f"<!-- {MARKER_PREFIX} expiring {citation.ref} -->",
        (
            f"**Summary:** {count} automated {tests} have been switched off "
            f"(\"quarantined\") since {oldest.quarantined_on.isoformat()} because "
            f"of {citation.ref}, which is still open. Quarantines may last "
            f"{threshold_days} days, so this one {when}. A maintainer needs to "
            "decide what happens to these tests."
        ),
        "",
        "**What I need from you:** Pick one: get the cause fixed, reclassify the "
        "tests, or delete the coverage.",
        "",
        "---",
        "",
        "## Still open",
        "",
        f"- Citation: [{citation.ref}]({status.url}) — {status.title}",
        f"- Reason given in the feature files: {citation.reason}",
        f"- Limit: {threshold_days} days, enforced by the `Quarantine age` job in "
        "`.github/workflows/pr-validate.yml`.",
        "",
        f"## Quarantines (at `{sha[:12]}`)",
        "",
        "| Tag line | Level | Scenario(s) | Quarantined since |",
        "|---|---|---|---|",
        *_rows(items, repo, sha),
        "",
        "## Options",
        "",
        f"1. **Fix the cause.** Push {citation.ref} to a fix. When it closes, this "
        "workflow replaces this issue with one that lifts the quarantines.",
        "2. **Reclassify.** If the cause is CI infrastructure or an unshipped "
        "feature, move the tags to `@pending` or `@future` with a comment naming "
        "the blocker, as `docs/skills/test-authoring/quarantine-age/SKILL.md` "
        "describes, and delete the `# quarantine:` line.",
        "3. **Re-cite.** If the cited issue is the wrong cause, point the "
        "`# quarantine:` line at the right open issue. The age keeps counting from "
        "the original quarantine.",
        "",
        "Never raise `--max-days` or `--grace-days` to clear the gate.",
        "",
        "_Kept up to date by `.github/workflows/quarantine-followup.yml` "
        "(`scripts/quarantine_followup.py`). It closes this issue once the "
        "quarantines are gone or their cause closes._",
    ]
    return Followup(
        key=f"expiring {citation.ref}",
        title=(
            f"test: {count} skipped {tests} reach the quarantine time limit on "
            f"{fails_on.isoformat()} ({citation.ref} still open)"
        ),
        body="\n".join(lines) + "\n",
        labels=EXPIRING_LABELS,
    )


def desired_followups(
    items: list[Item],
    statuses: dict[str, CitationStatus],
    *,
    repo: str,
    sha: str,
    threshold_days: int,
    warn_days: int,
) -> tuple[list[Followup], list[str]]:
    groups: dict[str, list[Item]] = {}
    for item in items:
        assert item.block.citation is not None
        groups.setdefault(item.block.citation.ref, []).append(item)

    followups: list[Followup] = []
    notes: list[str] = []
    for ref, group in sorted(groups.items()):
        status = statuses[ref]
        if status.kind == "missing":
            notes.append(f"{ref}: not found on GitHub; fix the citation by hand")
            continue
        if status.closed:
            followups.append(lift_followup(status, group, repo=repo, sha=sha))
            continue
        ages = [i.age_days for i in group if i.age_days is not None]
        oldest = max(ages) if ages else None
        if oldest is not None and oldest >= threshold_days - warn_days:
            followups.append(
                expiring_followup(
                    status, group, repo=repo, sha=sha, threshold_days=threshold_days
                )
            )
        else:
            notes.append(
                f"{ref}: open; {len(group)} quarantine(s), oldest "
                f"{oldest if oldest is not None else '?'} of {threshold_days} days"
            )
    return followups, notes


_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b|(?<=`)[0-9a-f]{12}(?=`)")


def _without_sha(body: str) -> str:
    """A body with commit hashes blanked, so a moved main is not an edit.

    Line numbers stay, so a link that now points at the wrong line is
    refreshed.
    """
    return _SHA_RE.sub("<sha>", body.replace("\r\n", "\n"))


def plan_actions(followups: list[Followup], open_issues: list[dict[str, Any]]) -> Plan:
    plan = Plan()
    existing: dict[str, list[dict[str, Any]]] = {}
    for issue in open_issues:
        match = MARKER_RE.search(issue.get("body") or "")
        if match:
            existing.setdefault(match.group("key").strip(), []).append(issue)
    for issues in existing.values():
        issues.sort(key=lambda i: i["number"])

    wanted = {f.key for f in followups}
    for followup in followups:
        matches = existing.get(followup.key, [])
        if not matches:
            plan.actions.append(
                Action(
                    kind="create",
                    key=followup.key,
                    title=followup.title,
                    body=followup.body,
                    labels=followup.labels,
                )
            )
            continue
        keeper, duplicates = matches[0], matches[1:]
        if keeper.get("title") != followup.title or _without_sha(
            keeper.get("body") or ""
        ) != _without_sha(followup.body):
            plan.actions.append(
                Action(
                    kind="update",
                    key=followup.key,
                    number=keeper["number"],
                    title=followup.title,
                    body=followup.body,
                )
            )
        else:
            plan.actions.append(Action(kind="keep", key=followup.key, number=keeper["number"]))
        for duplicate in duplicates:
            plan.actions.append(
                Action(
                    kind="close",
                    key=followup.key,
                    number=duplicate["number"],
                    comment=f"Duplicate of #{keeper['number']}, which tracks the same quarantine follow-up.",
                    reason="not_planned",
                )
            )

    for key, issues in sorted(existing.items()):
        if key in wanted:
            continue
        kind, _, ref = key.partition(" ")
        if kind == "expiring":
            why = (
                f"No quarantine citing {ref} is near its time limit any more: the "
                "tags were lifted, reclassified or re-cited, or the cause closed "
                "(a lift issue replaces this one)."
            )
        else:
            why = (
                f"No quarantine cites {ref} as closed any more: the quarantines "
                "were lifted or re-cited, or the citation was reopened."
            )
        for issue in issues:
            plan.actions.append(
                Action(
                    kind="close",
                    key=key,
                    number=issue["number"],
                    comment=why + " Closed by the quarantine follow-up workflow.",
                    reason="completed",
                )
            )
    return plan


def apply_plan(plan: Plan, github: GitHub, repo: str) -> list[str]:
    done = []
    for action in plan.actions:
        if action.kind == "create":
            number = github.create_issue(repo, action.title, action.body, action.labels)
            done.append(f"created #{number} ({action.key})")
        elif action.kind == "update":
            assert action.number is not None
            github.update_issue(repo, action.number, title=action.title, body=action.body)
            done.append(f"updated #{action.number} ({action.key})")
        elif action.kind == "close":
            assert action.number is not None
            github.comment(repo, action.number, action.comment)
            github.update_issue(
                repo, action.number, state="closed", state_reason=action.reason
            )
            done.append(f"closed #{action.number} ({action.key})")
    return done


def describe_plan(plan: Plan, *, show_bodies: bool) -> str:
    lines = []
    for action in plan.actions:
        target = f"#{action.number}" if action.number else "new issue"
        if action.kind == "keep":
            lines.append(f"KEEP   {target} [{action.key}] already up to date")
        elif action.kind == "close":
            lines.append(f"CLOSE  {target} [{action.key}] as {action.reason}: {action.comment}")
        else:
            label_text = f" labels={','.join(action.labels)}" if action.labels else ""
            lines.append(
                f"{action.kind.upper():<6} {target} [{action.key}]{label_text}\n"
                f"       title: {action.title}"
            )
            if show_bodies:
                lines.append("       body:")
                lines.extend(f"       | {line}" for line in action.body.splitlines())
    for note in plan.notes:
        lines.append(f"NOTE   {note}")
    return "\n".join(lines) if lines else "Nothing to do: no quarantines need a follow-up."


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open or update follow-up issues for @quarantine citations."
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "projectbluefin/testsuite"))
    parser.add_argument(
        "--sha",
        default=os.environ.get("GITHUB_SHA", ""),
        help="Commit for file:line links (default: $GITHUB_SHA, else git HEAD)",
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--max-days", type=int, default=QUARANTINE_MAX_DAYS)
    parser.add_argument(
        "--grace-days",
        type=int,
        default=0,
        help="Pass the same value the Quarantine age job uses (default: %(default)s)",
    )
    parser.add_argument("--warn-days", type=int, default=WARN_DAYS)
    parser.add_argument(
        "--today", type=date.fromisoformat, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing")
    parser.add_argument(
        "--no-bodies", action="store_true", help="With --dry-run, omit issue bodies"
    )
    return parser.parse_args(argv)


def head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() or "main"


def run(args: argparse.Namespace, github: GitHub) -> tuple[Plan, list[str]]:
    repo_root = args.repo_root.resolve()
    today = args.today or datetime.now(timezone.utc).date()
    sha = args.sha or head_sha(repo_root)
    threshold = args.max_days + args.grace_days

    items, problems = collect_items(repo_root, today)
    refs = sorted({i.block.citation.ref for i in items if i.block.citation})
    statuses = {}
    for ref in refs:
        repo, number = ref.split("#")
        statuses[ref] = github.citation_status(repo, int(number))
    followups, notes = desired_followups(
        items,
        statuses,
        repo=args.repo,
        sha=sha,
        threshold_days=threshold,
        warn_days=args.warn_days,
    )
    plan = plan_actions(followups, github.open_issues(args.repo))
    plan.notes.extend(notes)
    plan.notes.extend(f"invalid citation (fails PR validation): {p}" for p in problems)
    return plan, [i.block.citation.ref for i in items if i.block.citation]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    github = GitHub()
    plan, cited = run(args, github)
    print(f"{len(cited)} cited quarantine(s); {len(set(cited))} distinct citation(s).")
    if args.dry_run:
        print("DRY RUN: nothing is written.")
        print(describe_plan(plan, show_bodies=not args.no_bodies))
        report = describe_plan(plan, show_bodies=False)
    else:
        done = apply_plan(plan, github, args.repo)
        print(describe_plan(plan, show_bodies=False))
        report = "\n".join(done) or "No issue changes."
        print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Quarantine follow-up\n\n```\n" + describe_plan(plan, show_bodies=False) + "\n```\n")
            if not args.dry_run:
                handle.write("\n```\n" + report + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
