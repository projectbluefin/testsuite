#!/usr/bin/env python3
"""Fail when @quarantine scenarios have aged past the allowed threshold."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

QUARANTINE_MAX_DAYS = 30
RECOMMENDED_ACTION = (
    "Fix it, or convert it to @future/@pending if it covers a planned feature."
)


@dataclass(frozen=True)
class FeatureScenario:
    feature_file: Path
    name: str
    tags: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class QuarantineEntry:
    feature_file: Path
    scenario_name: str
    quarantined_on: date
    age_days: int
    threshold_days: int
    date_source: str = "history"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail CI when @quarantine scenarios are older than the allowed age."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=QUARANTINE_MAX_DAYS,
        help="Base maximum allowed quarantine age in days (default: %(default)s)",
    )
    parser.add_argument(
        "--grace-days",
        type=int,
        default=0,
        help=(
            "Additional rollout grace days on top of --max-days "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print all current quarantine entries as JSON and exit 0. "
            "Used by workflow summaries; does not enforce expiration."
        ),
    )
    return parser.parse_args()


def parse_feature_scenarios(content: str, feature_file: Path) -> list[FeatureScenario]:
    feature_tags: tuple[str, ...] = ()
    pending_tags: list[str] = []
    scenarios: list[FeatureScenario] = []

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("@"):
            pending_tags.extend(
                token[1:] for token in stripped.split() if token.startswith("@")
            )
            continue

        if stripped.startswith("Feature:"):
            feature_tags = tuple(pending_tags)
            pending_tags = []
            continue

        if stripped.startswith(("Scenario:", "Scenario Outline:")):
            _, scenario_name = stripped.split(":", 1)
            scenarios.append(
                FeatureScenario(
                    feature_file=feature_file,
                    name=scenario_name.strip(),
                    tags=tuple(feature_tags + tuple(pending_tags)),
                    line_number=line_number,
                )
            )
            pending_tags = []
            continue

        if stripped.startswith(("Rule:", "Background:", "Examples:")):
            pending_tags = []

    return scenarios


def iter_feature_files(repo_root: Path) -> Iterable[Path]:
    tests_root = repo_root / "tests"
    yield from sorted(tests_root.rglob("*.feature"))


def find_quarantined_scenarios(repo_root: Path) -> list[FeatureScenario]:
    quarantined: list[FeatureScenario] = []
    for feature_file in iter_feature_files(repo_root):
        content = feature_file.read_text(encoding="utf-8")
        for scenario in parse_feature_scenarios(content, feature_file):
            if "quarantine" in scenario.tags:
                quarantined.append(scenario)
    return quarantined


def git(*args: str, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_git_date(date_text: str) -> datetime:
    return datetime.fromisoformat(date_text.strip())


def file_history_entries(
    repo_root: Path, feature_file: Path
) -> list[tuple[str, datetime, str]]:
    """Return (sha, author date, path at that commit), oldest first.

    git ignores --follow when --reverse is given, so history is read newest
    first and reversed here; --name-only supplies each commit's path, which
    differs from the current one before a rename.
    """
    relative_path = str(feature_file.relative_to(repo_root))
    result = git(
        "log",
        "--follow",
        "--name-only",
        "--format=%x00%H%x09%aI",
        "--",
        relative_path,
        repo_root=repo_root,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git log failed for {relative_path}")

    history: list[tuple[str, datetime, str]] = []
    for record in result.stdout.split("\x00"):
        lines = [line for line in record.splitlines() if line.strip()]
        if not lines:
            continue
        sha, date_text = lines[0].split("\t", 1)
        path = lines[-1] if len(lines) > 1 else relative_path
        history.append((sha, parse_git_date(date_text), path))
    history.reverse()
    return history


def file_last_modified_date(repo_root: Path, feature_file: Path) -> date:
    relative_path = str(feature_file.relative_to(repo_root))
    result = git(
        "log",
        "-1",
        "--format=%aI",
        "--",
        relative_path,
        repo_root=repo_root,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            result.stderr.strip() or f"Unable to determine fallback date for {relative_path}"
        )
    return parse_git_date(result.stdout.strip()).date()


def scenario_quarantine_dates(
    repo_root: Path, feature_file: Path, scenario_names: set[str]
) -> dict[str, tuple[date, str]]:
    history = file_history_entries(repo_root, feature_file)
    first_seen: dict[str, tuple[date, str]] = {}

    for sha, committed_at, path_at_commit in history:
        show = git("show", f"{sha}:{path_at_commit}", repo_root=repo_root)
        if show.returncode != 0:
            continue

        scenarios = parse_feature_scenarios(show.stdout, feature_file)
        quarantined_here = {
            scenario.name for scenario in scenarios if "quarantine" in scenario.tags
        }

        for scenario_name in scenario_names - first_seen.keys():
            if scenario_name in quarantined_here:
                first_seen[scenario_name] = (committed_at.date(), "history")

        if len(first_seen) == len(scenario_names):
            return first_seen

    fallback_date = file_last_modified_date(repo_root, feature_file)
    for scenario_name in scenario_names - first_seen.keys():
        first_seen[scenario_name] = (fallback_date, "fallback:file-last-modified")
    return first_seen


def build_quarantine_entries(
    scenarios: Iterable[FeatureScenario],
    *,
    today: date,
    max_days: int,
    grace_days: int,
    repo_root: Path,
) -> list[QuarantineEntry]:
    threshold_days = max_days + grace_days
    scenarios_by_file: dict[Path, list[FeatureScenario]] = {}
    for scenario in scenarios:
        scenarios_by_file.setdefault(scenario.feature_file, []).append(scenario)

    entries: list[QuarantineEntry] = []
    for feature_file, file_scenarios in sorted(scenarios_by_file.items()):
        names = {scenario.name for scenario in file_scenarios}
        quarantine_dates = scenario_quarantine_dates(repo_root, feature_file, names)
        for scenario in file_scenarios:
            quarantined_on, date_source = quarantine_dates[scenario.name]
            entries.append(
                QuarantineEntry(
                    feature_file=scenario.feature_file.relative_to(repo_root),
                    scenario_name=scenario.name,
                    quarantined_on=quarantined_on,
                    age_days=(today - quarantined_on).days,
                    threshold_days=threshold_days,
                    date_source=date_source,
                )
            )

    return sorted(
        entries,
        key=lambda entry: (-entry.age_days, str(entry.feature_file), entry.scenario_name),
    )


def find_expired_quarantines(
    entries: Iterable[QuarantineEntry],
) -> list[QuarantineEntry]:
    return [entry for entry in entries if entry.age_days > entry.threshold_days]


def format_report(
    expired_entries: Iterable[QuarantineEntry], *, max_days: int, grace_days: int
) -> str:
    expired = list(expired_entries)
    threshold_days = max_days + grace_days
    if not expired:
        return (
            f"OK: no @quarantine scenarios exceed {threshold_days} days "
            f"({max_days} day limit + {grace_days} grace days)."
        )

    lines = [
        (
            f"ERROR: Found {len(expired)} @quarantine scenario(s) older than "
            f"{threshold_days} days ({max_days} day limit + {grace_days} grace days)."
        ),
        "",
    ]
    for entry in expired:
        lines.extend(
            [
                f"- Feature file: {entry.feature_file}",
                f"  Scenario: {entry.scenario_name}",
                f"  Date quarantined: {entry.quarantined_on.isoformat()}",
                f"  Age: {entry.age_days} days",
                f"  Action: {RECOMMENDED_ACTION}",
                f"  Date source: {entry.date_source}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def format_json(entries: Iterable[QuarantineEntry]) -> str:
    payload = []
    for entry in entries:
        item = asdict(entry)
        item["feature_file"] = str(entry.feature_file)
        item["quarantined_on"] = entry.quarantined_on.isoformat()
        item["days"] = item.pop("age_days")
        payload.append(item)
    return json.dumps(payload, sort_keys=True)


def validate_args(args: argparse.Namespace) -> None:
    if args.max_days < 0:
        raise ValueError("--max-days must be zero or greater")
    if args.grace_days < 0:
        raise ValueError("--grace-days must be zero or greater")


def main() -> int:
    args = parse_args()
    validate_args(args)

    repo_root = args.repo_root.resolve()
    today = datetime.now(timezone.utc).date()
    scenarios = find_quarantined_scenarios(repo_root)
    entries = build_quarantine_entries(
        scenarios,
        today=today,
        max_days=args.max_days,
        grace_days=args.grace_days,
        repo_root=repo_root,
    )
    if args.json:
        print(format_json(entries))
        return 0
    expired = find_expired_quarantines(entries)
    print(format_report(expired, max_days=args.max_days, grace_days=args.grace_days))
    return 1 if expired else 0


if __name__ == "__main__":
    raise SystemExit(main())
