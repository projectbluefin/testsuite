#!/usr/bin/env python3
"""Validate docs/skills/ files and general markdown hygiene."""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml")
    raise SystemExit(1) from exc

ROOT = Path(__file__).resolve().parents[1]

ERRORS: list[str] = []
WARNINGS: list[str] = []


def error(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def collect_md_files() -> list[Path]:
    # Prefer tracked files via git so untracked working artifacts are not linted.
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        files = [ROOT / line for line in proc.stdout.splitlines() if line]
        return sorted(files)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        if ".worktrees" in path.parts:
            continue
        parts = set(path.parts)
        if parts & {"node_modules", "__pycache__", ".venv"}:
            continue
        if ".github/ISSUE_TEMPLATE" in str(path):
            continue
        files.append(path)
    return sorted(files)


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    try:
        data = yaml.safe_load(parts[1])
        if isinstance(data, dict):
            return data, parts[2]
    except yaml.YAMLError:
        pass
    return None, text


def heading_level(line: str) -> int | None:
    m = re.match(r"^(#{1,6})\s+\S", line)
    if m:
        return len(m.group(1))
    return None


def validate_general(path: Path, text: str) -> None:
    lines = text.splitlines()
    in_fence = False
    fence = ""
    h1_count = 0
    for i, line in enumerate(lines, 1):
        if not in_fence and re.match(r"^(```|~~~)\s*\S*$", line):
            in_fence = True
            fence = line[:3]
            continue
        if in_fence:
            if line.startswith(fence):
                in_fence = False
            continue
        lvl = heading_level(line)
        if lvl == 1:
            h1_count += 1
        if lvl and lvl >= 5:
            error(f"{path}:{i}: H{lvl} heading (max H4)")
    if h1_count == 0:
        error(f"{path}: missing H1")
    elif h1_count > 1:
        error(f"{path}: multiple H1s ({h1_count})")


def validate_links(path: Path, text: str) -> None:
    """Check relative links point to existing files. External links are skipped."""
    base = path.parent
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        url = match.group(2)
        # Strip anchors and query strings
        bare = url.split("#")[0].split("?")[0]
        if not bare or re.match(r"^(https?://|mailto:|tel:)", bare):
            continue
        target = (base / bare).resolve()
        if not target.exists():
            try:
                display = target.relative_to(ROOT)
            except ValueError:
                # Target resolved outside ROOT (e.g. `../../nope.md`); show the
                # absolute path so the run reports a FAIL: line instead of a
                # traceback.
                display = target
            error(f"{path}: broken relative link '{url}' -> {display}")


CATALOG_FIELDS = (
    "id",
    "version",
    "last_updated",
    "one_line_purpose",
    "entry_point",
    "category",
    "status",
    "tags",
)
CATEGORIES = {"ci-ops", "test-authoring", "meta"}
STATUSES = {"active", "deprecated", "reserved"}


def validate_catalog_frontmatter(path: Path, fm: dict) -> None:
    """SKILL.md front matter must satisfy the shared factory catalog schema.

    Mirrors projectbluefin/common's docs/skills/index.schema.json so the
    generated catalog in docs/skills/index.json stays valid.
    """
    rel = path.relative_to(ROOT).as_posix()
    for field in CATALOG_FIELDS:
        if not fm.get(field):
            error(f"{path}: frontmatter missing '{field}' (required by docs/skills/index.schema.json)")
    category = fm.get("category")
    if category is not None and not isinstance(category, str):
        error(f"{path}: category must be one of {sorted(CATEGORIES)} (got {category!r})")
    elif category and category not in CATEGORIES:
        error(f"{path}: category '{category}' not in {sorted(CATEGORIES)}")
    status = fm.get("status")
    if status is not None and not isinstance(status, str):
        error(f"{path}: status must be one of {sorted(STATUSES)} (got {status!r})")
    elif status and status not in STATUSES:
        error(f"{path}: status '{status}' not in {sorted(STATUSES)}")
    if fm.get("id") and fm.get("name") and fm["id"] != fm["name"]:
        error(f"{path}: id '{fm['id']}' does not match name '{fm['name']}'")
    if fm.get("entry_point") and fm["entry_point"] != rel:
        error(f"{path}: entry_point '{fm['entry_point']}' does not match its own path '{rel}'")
    lu = fm.get("last_updated")
    if lu and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(lu)):
        error(f"{path}: last_updated '{lu}' is not YYYY-MM-DD")
    olp = fm.get("one_line_purpose")
    if olp and len(str(olp)) > 120:
        error(f"{path}: one_line_purpose exceeds 120 characters")
    tags = fm.get("tags")
    if tags is not None and (not isinstance(tags, list) or not tags):
        error(f"{path}: tags must be a non-empty list")


def validate_skill(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        error(f"{path}: missing YAML frontmatter")
        return
    name = fm.get("name")
    desc = fm.get("description")
    if not name:
        error(f"{path}: frontmatter missing 'name'")
    if not desc:
        error(f"{path}: frontmatter missing 'description'")
    lines = text.splitlines()
    is_skill_md = path.name == "SKILL.md"
    is_index = path.name == "index.md" and path.parent.name == "skills"
    is_reference = path.parent.name == "references"
    if is_skill_md and not is_index:
        expected_dir = path.parent.name
        if name and name != expected_dir:
            error(f"{path}: frontmatter name '{name}' does not match directory '{expected_dir}'")
        validate_catalog_frontmatter(path, fm)
    elif is_reference:
        if name and path.stem != name:
            warn(f"{path}: frontmatter name '{name}' does not match filename '{path.stem}'")
    if is_skill_md:
        if len(lines) > 500:
            error(f"{path}: SKILL.md exceeds 500 lines ({len(lines)})")
    else:
        if len(lines) > 200:
            error(f"{path}: reference exceeds 200 lines ({len(lines)})")
    validate_general(path, text)
    validate_links(path, text)


def validate_other(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    validate_general(path, text)
    validate_links(path, text)


def validate_router() -> None:
    """docs/SKILL.md is the factory-contract entry point; it must exist."""
    router = ROOT / "docs" / "SKILL.md"
    if not router.exists():
        error("docs/SKILL.md is missing (required by the factory onboarding contract)")
        return
    fm, _ = parse_frontmatter(router.read_text(encoding="utf-8"))
    if fm is None:
        error("docs/SKILL.md: missing YAML frontmatter")
        return
    validate_catalog_frontmatter(router, fm)


def main() -> int:
    for path in collect_md_files():
        rel = path.relative_to(ROOT)
        if str(rel) == "docs/SKILL.md":
            validate_other(path)
        elif "docs/skills/" in str(rel) and path.name.endswith(".md"):
            validate_skill(path)
        else:
            validate_other(path)

    validate_router()

    if WARNINGS:
        print("\n".join(f"WARN: {w}" for w in WARNINGS))
    if ERRORS:
        print("\n".join(f"FAIL: {e}" for e in ERRORS))
        return 1
    print("All docs validation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
