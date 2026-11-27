#!/usr/bin/env python3
"""GNOME OS scheduled extension-validation attribution.

Supports the scheduled validation workflow (#1259, step 6 of #909). Pure logic
for the four things the workflow host job needs:

  - classify()          bucket a run outcome as extension vs infrastructure
  - select_baseline()   pick the most recent passing GNOME OS build for a profile
  - marker()/find_existing_issue()  find-or-update by hidden body marker
  - build_issue_body()  render the issue body with its attribution line

The workflow drives this CLI; the pure functions are unit-tested and the gh
calls stay in the trusted host-side job. The baseline store is the JSON file the
scheduled workflow maintains on its dedicated branch (see docs/skills/ci-ops).

Usage:
  extension_baseline.py classify --outcome OUTCOME.json
  extension_baseline.py select-baseline --store STORE.json PROFILE
  extension_baseline.py find-issue --issues ISSUES.jsonl PROFILE
  extension_baseline.py body --profile PROFILE --candidate CAND.json --baseline BASE.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Hidden marker the host job searches for when finding the issue to update.
# Only issues filed by github-actions[bot] that carry this marker are edited.
MARKER_PREFIX = "<!-- extension-validation: "
MARKER_SUFFIX = " -->"

# Infrastructure/harness failures are reported separately from extension
# failures: they mean the guest never ran the scenarios, so there is nothing to
# attribute to GNOME OS or the extension. These substrings come from the gate's
# reason string (scripts/extension_validation.py) and the runner's own failures.
INFRA_MARKERS = (
    "missing results",
    "no scenario passed",
    "empty results",
    "failed to boot",
    "boot failure",
    "hook-error",
    "image not found",
    "image resolution failed",
    "no such image",
)


def classify(outcome: dict[str, Any]) -> str:
    """Return 'extension', 'infrastructure', or 'pass' for a run outcome.

    A passed outcome is 'pass'. A failure is 'infrastructure' when the reason
    string or the explicit infra flag says the guest never ran the scenarios;
    otherwise it is a real extension/test failure, 'extension'.
    """
    if outcome.get("passed"):
        return "pass"
    if outcome.get("infra"):
        return "infrastructure"
    reason = str(outcome.get("reason", "")).lower()
    if any(marker in reason for marker in INFRA_MARKERS):
        return "infrastructure"
    return "extension"


def select_baseline(store: dict[str, list[dict[str, Any]]], profile: str) -> dict[str, Any] | None:
    """Return the most recent passing GNOME OS build for a profile, or None.

    The store maps profile -> ordered list of passing builds (oldest first).
    """
    for build in reversed(store.get(profile, [])):
        if build.get("passed", True):
            return build
    return None


def marker(profile: str) -> str:
    """Return the hidden body marker for a profile."""
    return f"{MARKER_PREFIX}{profile}{MARKER_SUFFIX}"


def find_existing_issue(issues: list[dict[str, Any]], profile: str) -> dict[str, Any] | None:
    """Return the bot-authored issue that already carries this profile's marker.

    The workflow passes the filtered list of issues filed by
    github-actions[bot]; this narrows to the one whose body has the marker so an
    update lands in place instead of opening a duplicate.
    """
    want = marker(profile)
    for issue in issues:
        if issue.get("bot") and want in issue.get("body", ""):
            return issue
    return None


def _digest(digest: str | None) -> str:
    """Return the full image digest. #1259 requires exact digests, so the
    71-char ``sha256:...`` string is printed verbatim (never truncated)."""
    if not digest:
        return "unknown"
    return digest


def attribution_line(profile: str, candidate: dict[str, Any], baseline: dict[str, Any] | None,
                     rerun: dict[str, Any] | None) -> str:
    """Return the one-line attribution for the issue.

    rerun is the result of re-running the identical artifact on the baseline.
    - No baseline recorded: cannot attribute yet.
    - Baseline reran and passed: a GNOME OS change between the two builds.
    - Baseline reran and failed: fails on both; extension or test at fault.
    """
    if not baseline:
        return (f"No earlier passing GNOME OS build is recorded for {profile}, so this "
                f"cannot yet be attributed to GNOME OS.")
    # An infrastructure/harness failure means the guest never ran the scenarios,
    # so nothing can be attributed to GNOME OS or the extension. The candidate
    # and the baseline rerun are both checked: a harness failure in either
    # outcome makes attribution inconclusive.
    if (candidate.get("classification") == "infrastructure"
            or (rerun and rerun.get("classification") == "infrastructure")):
        return ("Inconclusive: the failure is an infrastructure/harness failure in "
                "GNOME OS validation, not an extension or test result. Fix the harness "
                "before attributing this to GNOME OS.")
    base = f"GNOME OS {baseline.get('os_release', 'build')} ({_digest(baseline.get('digest'))})"
    cand = f"GNOME OS {candidate.get('os_release', 'devel')} ({_digest(candidate.get('digest'))})"
    if not rerun:
        return (f"Attribution: rerun on {base} has not run yet; compare against {cand} "
                f"once it does.")
    if rerun.get("passed"):
        return (f"Attribution: PASSES on {base} but fails on {cand}. The change is in "
                f"GNOME OS between the two builds; name a culprit only after a bisect.")
    return (f"Attribution: FAILS on {base} as well as {cand}. Not a GNOME OS "
            f"regression; the extension or its test is at fault.")


def build_issue_body(profile: str, candidate: dict[str, Any], baseline: dict[str, Any] | None,
                     rerun: dict[str, Any] | None) -> str:
    """Render the issue body: a one-line summary, the marker, then the detail."""
    summary = (f"{profile} failed the GNOME OS extension-validation gate on the devel image.")
    lines = [summary, "", marker(profile), "", "---", "", "## Attribution",
             attribution_line(profile, candidate, baseline, rerun), ""]
    lines += ["## Candidate build",
              f"- **Image:** {candidate.get('os_release', 'devel')} (`{_digest(candidate.get('digest'))}`)",
              f"- **Candidate digest:** {_digest(candidate.get('devel_digest', candidate.get('digest')))}",
              f"- **Base digest:** {_digest(candidate.get('base_digest'))}",
              f"- **Run:** {candidate.get('run_url', 'n/a')}",
              f"- **Shell version:** {candidate.get('shell_version', 'n/a')}",
              f"- **Scenarios:** {', '.join(candidate.get('scenarios', []) or ['(none recorded)'])}",
              ""]
    if baseline:
        lines += ["## Baseline build",
                  f"- **Image:** {baseline.get('os_release', 'build')} (`{_digest(baseline.get('digest'))}`)",
                  f"- **Baseline digest:** {_digest(baseline.get('devel_digest', baseline.get('digest')))}",
                  f"- **Base digest:** {_digest(baseline.get('base_digest'))}",
                  f"- **Date:** {baseline.get('date', 'n/a')}",
                  f"- **Result on baseline:** {('passes' if (rerun and rerun.get('passed')) else 'fails')}",
                  ""]
    else:
        lines += ["## Baseline build",
                  "- **No earlier passing GNOME OS build is recorded for this profile yet.**",
                  ""]
    lines += ["## Details",
              f"- **Gate verdict:** {candidate.get('reason', 'non-success scenarios present')}",
              f"- **Classification:** {candidate.get('classification', 'extension')}",
              f"- **Extension artifact:** {candidate.get('extension_zip', 'n/a')}",
              f"- **Extension sha256:** {candidate.get('extension_sha256', 'n/a')}",
              ("- **Next step:** infrastructure/harness failure in GNOME OS validation; the "
               "guest never ran the scenarios. Fix the harness before attributing this to "
               "GNOME OS." if (candidate.get("classification") == "infrastructure"
                               or (rerun and rerun.get("classification") == "infrastructure")) else
               "- **Next step:** if this is a GNOME OS change, open a follow-up and bisect the "
               "image range above to name the culprit commit. Do not file a fix PR for the "
               "extension here."),
              ""]
    return "\n".join(lines)


def merge_rerun_outcomes(report: dict, rerun_dir: str | os.PathLike) -> None:
    """Attach each rerun job's outcome to its profile in the attribution report.

    The rerun job uploads ``rerun-outcomes-<profile>/outcomes/<profile>.json``; the
    file job merges them so attribution can say whether the rerun passed on the
    baseline. A missing rerun leaves the profile without a ``rerun`` key.

    The download-artifact merge nests each artifact under its own name, so the
    glob is recursive (same layout the attribution job downloads).
    """
    for path in glob.glob(str(Path(rerun_dir) / "**" / "*.json"), recursive=True):
        try:
            outcome = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        profile = outcome.get("profile")
        if profile and profile in report.get("profiles", {}):
            report["profiles"][profile]["rerun"] = {
                "passed": outcome.get("passed"),
                "reason": outcome.get("reason", ""),
                "run_url": outcome.get("run_url", ""),
                "classification": outcome.get("classification", ""),
            }


def bot_issues(token: str) -> list[dict[str, Any]]:
    """Return the bot-authored issues as JSON objects with a ``bot`` flag.

    ``gh issue list --json author`` returns each author as
    ``{"login": ..., "is_bot": ...}``; match the validation bot by login so a
    change in the author payload shape can no longer hide every issue. The
    workflow limits matching to ``github-actions[bot]`` (#1259) so the weekly
    run updates its own issues and never edits a maintainer's.
    """
    out = subprocess.run(["gh", "issue", "list", "--state", "all", "--limit", "200",
                          "--json", "number,title,body,author"],
                         capture_output=True, text=True)
    raw = json.loads(out.stdout) if out.stdout.strip() else []
    issues = []
    for item in raw:
        author = item.get("author", {})
        if author.get("login") in ("github-actions[bot]", "app/github-actions"):
            item["bot"] = True
            issues.append(item)
    return issues


def _edit_issue(token: str, number: int, body: str) -> None:
    Path(".issue-body.md").write_text(body)
    subprocess.run(["gh", "issue", "edit", str(number), "--body-file", ".issue-body.md"],
                   check=True)


def _create_issue(token: str, profile: str, body: str) -> int:
    Path(".issue-body.md").write_text(body)
    title = f"[{profile}] GNOME OS extension validation failed"
    proc = subprocess.run(["gh", "issue", "create", "--title", title, "--body-file", ".issue-body.md"],
                          capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        tail = line.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return int(tail)
    raise RuntimeError(f"gh issue create failed: {proc.stderr}")


def file_issues(report_path: str, token: str) -> int:
    """File or update one issue per failed profile, attributed to its baseline.

    Reads the attribution report, lists bot-authored issues, and for each failed
    profile either edits the issue already carrying its marker or opens a new
    one. Returns the number of issues acted on.
    """
    report = json.loads(Path(report_path).read_text())
    if not token:
        print("file-issues: GH_TOKEN is not set; aborting", file=sys.stderr)
        return 1
    issues = bot_issues(token)
    acted = 0
    for profile, data in report.get("profiles", {}).items():
        body = build_issue_body(profile, data, data.get("baseline"), data.get("rerun"))
        issue = find_existing_issue(issues, profile)
        if issue:
            _edit_issue(token, issue["number"], body)
            print(f"updated issue #{issue['number']} for {profile}")
        else:
            number = _create_issue(token, profile, body)
            print(f"created issue #{number} for {profile}")
        acted += 1
    return acted


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text())


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("classify", help="bucket a run outcome")
    p.add_argument("--outcome", required=True, help="outcome JSON file")

    p = sub.add_parser("select-baseline", help="print the most recent passing build")
    p.add_argument("--store", required=True, help="baseline store JSON file")
    p.add_argument("profile")

    p = sub.add_parser("find-issue", help="print the matching bot issue, or nothing")
    p.add_argument("--issues", required=True, help="JSON-lines file of bot issues")
    p.add_argument("profile")

    p = sub.add_parser("body", help="render the issue body")
    p.add_argument("--profile", required=True)
    p.add_argument("--candidate", required=True, help="candidate outcome JSON file")
    p.add_argument("--baseline", help="baseline build JSON file (optional)")
    p.add_argument("--rerun", help="rerun outcome JSON file (optional)")

    p = sub.add_parser("file-issues", help="file or update attribution issues from a report")
    p.add_argument("--report", required=True, help="attribution report JSON file")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "classify":
        _emit(classify(_load(args.outcome)))
    elif args.command == "select-baseline":
        store = _load(args.store)
        _emit(select_baseline(store, args.profile))
    elif args.command == "find-issue":
        issues = [json.loads(line) for line in Path(args.issues).read_text().splitlines() if line.strip()]
        issue = find_existing_issue(issues, args.profile)
        if issue:
            _emit(issue)
    elif args.command == "body":
        candidate = _load(args.candidate)
        baseline = _load(args.baseline) if args.baseline else None
        rerun = _load(args.rerun) if args.rerun else None
        print(build_issue_body(args.profile, candidate, baseline, rerun))
    elif args.command == "file-issues":
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("file-issues: GH_TOKEN is not set; aborting", file=sys.stderr)
            return 1
        file_issues(args.report, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
