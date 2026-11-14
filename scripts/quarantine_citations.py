#!/usr/bin/env python3
"""Require a machine-readable citation for every @quarantine tag.

A quarantine must name the open issue or pull request that caused it, on a
comment line directly above the tag line:

    # quarantine: projectbluefin/dakota#1875 power-status-color missing from dakota:testing
    @extensions @quarantine
    Scenario: Power status color extension is enabled

The format is exact so scripts/quarantine_followup.py can ask GitHub whether
the cause is closed: ``# quarantine: projectbluefin/<repo>#<number> <reason>``.
The reason is required, one line, and free text.

The citation sits in the run of comment and tag lines that ends at the tagged
keyword (``Feature:``, ``Rule:``, ``Scenario:``, ``Scenario Outline:`` or
``Examples:``), with no blank line in between. A feature-level tag covers every
scenario in the file; a scenario that also carries its own ``@quarantine``
needs its own citation. A ``# quarantine:`` line with no ``@quarantine`` tag
under it is an error too, so a lifted quarantine cannot leave a stale citation.

Exit status 1 lists every problem as ``file:line: message``; under GitHub
Actions each one is also printed as an ``::error`` annotation.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CITATION_FORMAT = "# quarantine: projectbluefin/<repo>#<number> <short reason>"

# Any comment that is trying to be a citation, so a malformed one is reported
# instead of silently ignored. The old free-text "# Quarantined: ..." comments
# do not match (the colon must follow "quarantine" directly).
CITATION_INTENT_RE = re.compile(r"^#\s*quarantine\s*:", re.IGNORECASE)
CITATION_RE = re.compile(
    r"^#\s*quarantine:\s+"
    r"(?P<repo>projectbluefin/[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)"
    r"\s+(?P<reason>\S.*?)\s*$"
)

# Keywords a tag block can sit on, longest first so "Scenario Outline:" is not
# read as "Scenario:".
TAGGABLE_KEYWORDS = (
    "Scenario Outline",
    "Scenario Template",
    "Scenarios",
    "Scenario",
    "Examples",
    "Example",
    "Feature",
    "Rule",
)
OTHER_KEYWORDS = ("Background",)
SCENARIO_KEYWORDS = frozenset(
    {"Scenario", "Scenario Outline", "Scenario Template", "Example"}
)
EXAMPLES_KEYWORDS = frozenset({"Examples", "Scenarios"})


@dataclass(frozen=True)
class Citation:
    repo: str
    number: int
    reason: str

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


@dataclass(frozen=True)
class Problem:
    feature_file: Path
    line: int
    message: str

    def format(self) -> str:
        return f"{self.feature_file}:{self.line}: {self.message}"


@dataclass
class QuarantineBlock:
    """One ``@quarantine`` tag and what it covers."""

    feature_file: Path
    tag_line: int
    level: str  # feature, rule, scenario or examples
    name: str
    keyword_line: int
    citation: Citation | None
    scenarios: list[str] = field(default_factory=list)


def parse_citation(line: str) -> Citation | None:
    """Return the citation on a stripped comment line, or None."""
    match = CITATION_RE.match(line.strip())
    if not match:
        return None
    return Citation(
        repo=match.group("repo"),
        number=int(match.group("number")),
        reason=match.group("reason"),
    )


def _keyword(stripped: str) -> tuple[str, str] | None:
    for keyword in TAGGABLE_KEYWORDS + OTHER_KEYWORDS:
        if stripped.startswith(keyword + ":"):
            return keyword, stripped[len(keyword) + 1 :].strip()
    return None


def _level(keyword: str) -> str:
    if keyword == "Feature":
        return "feature"
    if keyword == "Rule":
        return "rule"
    if keyword in EXAMPLES_KEYWORDS:
        return "examples"
    return "scenario"


def parse_feature(
    content: str, feature_file: Path
) -> tuple[list[QuarantineBlock], list[Problem]]:
    """Return every @quarantine block in one feature file and its problems."""
    blocks: list[QuarantineBlock] = []
    problems: list[Problem] = []

    # Comment and tag lines directly above the next keyword (a blank line or
    # any other line ends the run).
    run: list[tuple[int, str]] = []
    # Tags since the last keyword; a blank line does not drop them, matching
    # scripts/check_quarantine_age.py.
    pending_tags: list[tuple[int, str]] = []
    # Every citation-like comment line and whether a quarantine used it.
    citation_lines: dict[int, bool] = {}

    feature_block: QuarantineBlock | None = None
    rule_block: QuarantineBlock | None = None
    last_scenario: str | None = None

    def problem(line: int, message: str) -> None:
        problems.append(Problem(feature_file, line, message))

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            run = []
            continue
        if stripped.startswith("#"):
            if CITATION_INTENT_RE.match(stripped):
                citation_lines[line_number] = False
            run.append((line_number, stripped))
            continue
        if stripped.startswith("@"):
            for token in stripped.split():
                if token.startswith("@"):
                    pending_tags.append((line_number, token[1:]))
            run.append((line_number, stripped))
            continue

        found = _keyword(stripped)
        if found is None:
            # Description or step text: whatever ran above it is not a tag
            # block. Tags cannot precede plain text, so pending tags stay.
            run = []
            continue
        keyword, name = found

        quarantine_tags = [ln for ln, tag in pending_tags if tag == "quarantine"]
        if quarantine_tags and keyword in OTHER_KEYWORDS:
            problem(quarantine_tags[0], f"@quarantine cannot be applied to {keyword}:")
            quarantine_tags = []

        block: QuarantineBlock | None = None
        if quarantine_tags:
            run_lines = {ln for ln, _ in run}
            cited = [
                (ln, text) for ln, text in run if CITATION_INTENT_RE.match(text)
            ]
            citation: Citation | None = None
            if not cited:
                if quarantine_tags[0] in run_lines:
                    problem(
                        quarantine_tags[0],
                        f"@quarantine on {keyword} '{name}' has no citation; "
                        f"add '{CITATION_FORMAT}' on the line directly above "
                        "its tags",
                    )
                else:
                    problem(
                        quarantine_tags[0],
                        f"@quarantine on {keyword} '{name}' is separated from "
                        "its keyword by a blank line; put the tags and the "
                        f"'{CITATION_FORMAT}' line directly above it",
                    )
            elif len(cited) > 1:
                for ln, _ in cited:
                    citation_lines[ln] = True
                problem(
                    cited[1][0],
                    f"@quarantine on {keyword} '{name}' has {len(cited)} "
                    "citations; cite exactly one cause",
                )
            else:
                ln, text = cited[0]
                citation_lines[ln] = True
                citation = parse_citation(text)
                if citation is None:
                    problem(
                        ln,
                        f"malformed quarantine citation {text!r}; expected "
                        f"'{CITATION_FORMAT}' (exact owner/repo#N, repo under "
                        "projectbluefin/, then a reason)",
                    )
            block = QuarantineBlock(
                feature_file=feature_file,
                tag_line=quarantine_tags[0],
                level=_level(keyword),
                name=name,
                keyword_line=line_number,
                citation=citation,
            )
            blocks.append(block)
            if len(quarantine_tags) > 1:
                problem(quarantine_tags[1], "duplicate @quarantine tag")

        if keyword == "Feature":
            feature_block = block
            rule_block = None
        elif keyword == "Rule":
            rule_block = block
        elif keyword in SCENARIO_KEYWORDS:
            last_scenario = name
            for covering in (feature_block, rule_block, block):
                if covering is not None:
                    covering.scenarios.append(name)
        elif keyword in EXAMPLES_KEYWORDS and block is not None:
            # Examples-level tags quarantine rows of the outline above.
            block.name = last_scenario or name
            block.scenarios.append(last_scenario or name)

        pending_tags = []
        run = []

    for ln, used in sorted(citation_lines.items()):
        if not used:
            problem(
                ln,
                "quarantine citation with no @quarantine tag directly below it; "
                "delete the citation when the quarantine is lifted",
            )

    return blocks, problems


def iter_feature_files(repo_root: Path) -> Iterable[Path]:
    yield from sorted((repo_root / "tests").rglob("*.feature"))


def scan(repo_root: Path) -> tuple[list[QuarantineBlock], list[Problem]]:
    """Parse every feature file under tests/. Paths are repo-relative."""
    blocks: list[QuarantineBlock] = []
    problems: list[Problem] = []
    for feature_file in iter_feature_files(repo_root):
        relative = feature_file.relative_to(repo_root)
        file_blocks, file_problems = parse_feature(
            feature_file.read_text(encoding="utf-8"), relative
        )
        blocks.extend(file_blocks)
        problems.extend(file_problems)
    return blocks, problems


def format_report(blocks: list[QuarantineBlock], problems: list[Problem]) -> str:
    if not problems:
        return f"OK: {len(blocks)} @quarantine tag(s), each with a valid citation."
    lines = [f"ERROR: {len(problems)} quarantine citation problem(s):", ""]
    lines.extend(f"- {problem.format()}" for problem in problems)
    lines.extend(
        [
            "",
            f"Every @quarantine needs '{CITATION_FORMAT}' directly above its tags.",
            "See docs/skills/test-authoring/suite-map/SKILL.md (Quarantine citations).",
        ]
    )
    return "\n".join(lines)


def _annotation_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to scan (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    blocks, problems = scan(args.repo_root.resolve())
    print(format_report(blocks, problems))
    if problems and os.environ.get("GITHUB_ACTIONS") == "true":
        for item in problems:
            print(
                f"::error file={item.feature_file},line={item.line}::"
                f"{_annotation_escape(item.message)}"
            )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
