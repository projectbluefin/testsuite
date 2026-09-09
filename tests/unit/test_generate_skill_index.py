"""Unit tests for scripts/generate_skill_index.py.

This script is a required PR gate (``.github/workflows/docs-validate.yml``
runs ``python3 scripts/generate_skill_index.py --check``), so a regression
that drops one of the nine front-matter validations lets a malformed skill
into ``index.json`` with a green build, and a change to the ``--check``
date handling (reusing the committed ``generated_at`` rather than
``date.today()``) would make the gate fail every day after the catalog is
committed.

Covers: ``parse_frontmatter``, ``collect``, ``render_json``, ``render_md``
and ``main``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import generate_skill_index as gsi


def write_skill(root: Path, relpath: str, frontmatter: str, body: str = "# body\n") -> Path:
    """Create docs/skills/<relpath>/SKILL.md under ``root`` with ``frontmatter``."""
    path = root / "docs" / "skills" / relpath / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def base_frontmatter(**overrides) -> str:
    """Return a minimal valid front-matter block, as YAML text."""
    entry_point = overrides.pop("entry_point", "docs/skills/foo/SKILL.md")
    fields = {
        "id": "foo",
        "name": "foo",
        "one_line_purpose": "Do the foo thing.",
        "entry_point": entry_point,
        "category": "meta",
        "status": "active",
        "tags": "[foo, bar]",
        "description": "A description of foo.",
        "version": '"1.0"',
        "last_updated": '"2026-01-01"',
    }
    fields.update(overrides)
    return "\n".join(f"{k}: {v}" for k, v in fields.items())


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    """Point the module's path constants at an isolated tmp_path repo."""
    skills_dir = tmp_path / "docs" / "skills"
    monkeypatch.setattr(gsi, "ROOT", tmp_path)
    monkeypatch.setattr(gsi, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(gsi, "INDEX_JSON", skills_dir / "index.json")
    monkeypatch.setattr(gsi, "INDEX_MD", skills_dir / "index.md")
    return tmp_path


# ── parse_frontmatter ──────────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_parses_a_valid_yaml_block(self, tmp_path):
        path = write_skill(tmp_path, "foo", base_frontmatter())
        data = gsi.parse_frontmatter(path)
        assert data["id"] == "foo"
        assert data["tags"] == ["foo", "bar"]

    def test_missing_leading_marker_raises(self, tmp_path):
        path = tmp_path / "docs" / "skills" / "foo" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("name: foo\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="missing YAML front matter"):
            gsi.parse_frontmatter(path)

    def test_non_mapping_frontmatter_raises(self, tmp_path):
        path = tmp_path / "docs" / "skills" / "foo" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\n- one\n- two\n---\nbody\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="not a mapping"):
            gsi.parse_frontmatter(path)


# ── collect ────────────────────────────────────────────────────────────────


class TestCollect:
    def test_valid_skill_is_collected(self, tmp_path):
        write_skill(tmp_path, "foo", base_frontmatter())
        skills = gsi.collect()
        assert len(skills) == 1
        assert skills[0]["id"] == "foo"
        assert skills[0]["tags"] == ["foo", "bar"]
        assert skills[0]["version"] == "1.0"
        assert skills[0]["last_updated"] == "2026-01-01"

    def test_results_are_sorted_by_id(self, tmp_path):
        write_skill(
            tmp_path, "zeta",
            base_frontmatter(id="zeta", name="zeta", entry_point="docs/skills/zeta/SKILL.md"),
        )
        write_skill(
            tmp_path, "alpha",
            base_frontmatter(id="alpha", name="alpha", entry_point="docs/skills/alpha/SKILL.md"),
        )
        skills = gsi.collect()
        assert [s["id"] for s in skills] == ["alpha", "zeta"]

    def test_description_whitespace_is_normalised(self, tmp_path):
        write_skill(tmp_path, "foo", base_frontmatter(description='"line one\\n  line two"'))
        skills = gsi.collect()
        assert skills[0]["description"] == "line one line two"

    def test_doc_type_is_extracted_from_metadata(self, tmp_path):
        fm = base_frontmatter() + "\nmetadata:\n  type: manifest\n"
        write_skill(tmp_path, "foo", fm)
        skills = gsi.collect()
        assert skills[0]["doc_type"] == "manifest"

    def test_missing_metadata_omits_doc_type(self, tmp_path):
        write_skill(tmp_path, "foo", base_frontmatter())
        skills = gsi.collect()
        assert "doc_type" not in skills[0]

    @pytest.mark.parametrize("field", list(gsi.REQUIRED))
    def test_missing_required_field_fails_the_gate(self, tmp_path, field, capsys):
        fields = {
            "id": "foo",
            "name": "foo",
            "one_line_purpose": "Do the foo thing.",
            "entry_point": "docs/skills/foo/SKILL.md",
            "category": "meta",
            "status": "active",
            "tags": "[foo, bar]",
            "description": "A description of foo.",
            "version": '"1.0"',
            "last_updated": '"2026-01-01"',
        }
        del fields[field]
        fm = "\n".join(f"{k}: {v}" for k, v in fields.items())
        write_skill(tmp_path, "foo", fm)

        with pytest.raises(SystemExit):
            gsi.collect()
        assert f"missing {field}" in capsys.readouterr().err

    def test_invalid_category_fails_the_gate(self, tmp_path, capsys):
        write_skill(tmp_path, "foo", base_frontmatter(category="bogus"))
        with pytest.raises(SystemExit):
            gsi.collect()
        assert "category 'bogus' not in" in capsys.readouterr().err

    def test_invalid_status_fails_the_gate(self, tmp_path, capsys):
        write_skill(tmp_path, "foo", base_frontmatter(status="bogus"))
        with pytest.raises(SystemExit):
            gsi.collect()
        assert "status 'bogus' not in" in capsys.readouterr().err

    def test_entry_point_mismatch_fails_the_gate(self, tmp_path, capsys):
        write_skill(tmp_path, "foo", base_frontmatter(entry_point="docs/skills/wrong/SKILL.md"))
        with pytest.raises(SystemExit):
            gsi.collect()
        assert "does not match its own path" in capsys.readouterr().err

    def test_id_name_mismatch_fails_the_gate(self, tmp_path, capsys):
        write_skill(tmp_path, "foo", base_frontmatter(id="not-foo"))
        with pytest.raises(SystemExit):
            gsi.collect()
        assert "does not match name" in capsys.readouterr().err

    def test_multiple_errors_across_skills_are_all_reported(self, tmp_path, capsys):
        write_skill(tmp_path, "foo", base_frontmatter(category="bogus"))
        write_skill(
            tmp_path, "bar",
            base_frontmatter(id="bar", name="bar", entry_point="docs/skills/bar/SKILL.md", status="bogus"),
        )
        with pytest.raises(SystemExit):
            gsi.collect()
        err = capsys.readouterr().err
        assert "foo/SKILL.md" in err
        assert "bar/SKILL.md" in err

    def test_no_skills_returns_empty_list(self, tmp_path):
        (tmp_path / "docs" / "skills").mkdir(parents=True)
        assert gsi.collect() == []


# ── render_json / render_md ─────────────────────────────────────────────────


class TestRenderJson:
    def test_payload_shape(self):
        skills = [{"id": "foo"}]
        text = gsi.render_json(skills, "2026-01-01")
        payload = json.loads(text)
        assert payload == {
            "generated_at": "2026-01-01",
            "schema_version": gsi.SCHEMA_VERSION,
            "skills": skills,
        }

    def test_ends_with_a_trailing_newline(self):
        assert gsi.render_json([], "2026-01-01").endswith("\n")


class TestRenderMd:
    def test_includes_generated_date_and_count(self):
        skills = [
            {
                "id": "foo",
                "entry_point": "docs/skills/foo/SKILL.md",
                "category": "meta",
                "status": "active",
                "one_line_purpose": "Do the foo thing.",
            }
        ]
        text = gsi.render_md(skills, "2026-01-01")
        assert 'last_updated: "2026-01-01"' in text
        assert "Generated: 2026-01-01" in text
        assert "1 skills" in text

    def test_table_row_links_relative_to_skills_dir(self):
        skills = [
            {
                "id": "foo",
                "entry_point": "docs/skills/sub/foo/SKILL.md",
                "category": "meta",
                "status": "active",
                "one_line_purpose": "Purpose.",
            }
        ]
        text = gsi.render_md(skills, "2026-01-01")
        assert "| [foo](sub/foo/SKILL.md) | meta | active | Purpose. |" in text

    def test_empty_skills_still_renders_a_valid_document(self):
        text = gsi.render_md([], "2026-01-01")
        assert "0 skills" in text
        assert "| id | category | status | one-line purpose |" in text


# ── main ────────────────────────────────────────────────────────────────────


class TestMain:
    def test_write_mode_creates_index_json_and_md(self, tmp_path, monkeypatch):
        write_skill(tmp_path, "foo", base_frontmatter())
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py"])

        assert gsi.main() == 0
        assert gsi.INDEX_JSON.exists()
        assert gsi.INDEX_MD.exists()
        payload = json.loads(gsi.INDEX_JSON.read_text(encoding="utf-8"))
        assert payload["skills"][0]["id"] == "foo"

    def test_check_mode_fails_when_index_json_is_missing(self, tmp_path, monkeypatch, capsys):
        write_skill(tmp_path, "foo", base_frontmatter())
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 1
        assert "index.json is missing" in capsys.readouterr().out

    def test_check_mode_fails_when_index_json_is_stale(self, tmp_path, monkeypatch, capsys):
        write_skill(tmp_path, "foo", base_frontmatter())
        gsi.INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
        gsi.INDEX_JSON.write_text(
            json.dumps({"generated_at": "2020-01-01", "schema_version": "1.0", "skills": []}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 1
        assert "index.json is stale" in capsys.readouterr().out

    def test_check_mode_fails_when_index_md_is_stale(self, tmp_path, monkeypatch, capsys):
        write_skill(tmp_path, "foo", base_frontmatter())
        skills = gsi.collect()
        gsi.INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
        gsi.INDEX_JSON.write_text(gsi.render_json(skills, "2026-01-01"), encoding="utf-8")
        gsi.INDEX_MD.write_text("stale content\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 1
        assert "index.md is stale" in capsys.readouterr().out

    def test_check_mode_reuses_the_committed_generated_at_not_todays_date(
        self, tmp_path, monkeypatch, capsys
    ):
        """A regression that switches this to date.today() would make the
        docs gate fail every day after the catalog is committed, since the
        committed index.md always has a fixed generated_at."""
        write_skill(tmp_path, "foo", base_frontmatter())
        skills = gsi.collect()
        committed_date = "2020-06-15"
        gsi.INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
        gsi.INDEX_JSON.write_text(gsi.render_json(skills, committed_date), encoding="utf-8")
        gsi.INDEX_MD.write_text(gsi.render_md(skills, committed_date), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 0
        assert "in sync" in capsys.readouterr().out

    def test_check_mode_passes_when_everything_is_in_sync(self, tmp_path, monkeypatch, capsys):
        write_skill(tmp_path, "foo", base_frontmatter())
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py"])
        assert gsi.main() == 0  # write mode, populate the catalog
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 0
        assert "in sync (1 skills)" in capsys.readouterr().out


# ── repository invariant ────────────────────────────────────────────────────


class TestRepositoryInvariant:
    def test_committed_catalog_is_current(self, monkeypatch):
        """The same assertion docs-validate.yml makes, run in the unit suite."""
        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.setattr(gsi, "ROOT", repo_root)
        monkeypatch.setattr(gsi, "SKILLS_DIR", repo_root / "docs" / "skills")
        monkeypatch.setattr(gsi, "INDEX_JSON", repo_root / "docs" / "skills" / "index.json")
        monkeypatch.setattr(gsi, "INDEX_MD", repo_root / "docs" / "skills" / "index.md")
        monkeypatch.setattr(sys, "argv", ["generate_skill_index.py", "--check"])

        assert gsi.main() == 0
