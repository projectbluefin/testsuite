"""Unit tests for scripts/validate_docs.py."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import validate_docs as vd  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_globals():
    """Clear module-level ERRORS / WARNINGS between tests."""
    vd.ERRORS.clear()
    vd.WARNINGS.clear()
    yield
    vd.ERRORS.clear()
    vd.WARNINGS.clear()


# ── parse_frontmatter ─────────────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_valid_frontmatter_returns_dict_and_body(self):
        text = "---\nname: foo\ndescription: bar\n---\nBody text"
        fm, body = vd.parse_frontmatter(text)
        assert fm == {"name": "foo", "description": "bar"}
        assert "Body text" in body

    def test_no_frontmatter_returns_none_and_full_text(self):
        text = "# Title\nNo frontmatter here"
        fm, body = vd.parse_frontmatter(text)
        assert fm is None
        assert body == text

    def test_incomplete_delimiter_returns_none(self):
        text = "---\nname: foo\n"
        fm, body = vd.parse_frontmatter(text)
        assert fm is None

    def test_non_dict_yaml_returns_none(self):
        text = "---\n- item1\n- item2\n---\nBody"
        fm, body = vd.parse_frontmatter(text)
        assert fm is None

    def test_malformed_yaml_returns_none(self):
        text = "---\nkey: [unclosed\n---\nBody"
        fm, body = vd.parse_frontmatter(text)
        assert fm is None


# ── heading_level ─────────────────────────────────────────────────────────────


class TestHeadingLevel:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("# H1 title", 1),
            ("## H2 section", 2),
            ("### H3 sub", 3),
            ("#### H4 deep", 4),
            ("##### H5 too-deep", 5),
            ("###### H6 too-deep", 6),
        ],
    )
    def test_detects_heading_levels(self, line, expected):
        assert vd.heading_level(line) == expected

    def test_plain_text_is_not_a_heading(self):
        assert vd.heading_level("regular paragraph") is None

    def test_hash_without_space_is_not_a_heading(self):
        assert vd.heading_level("#nospace") is None

    def test_empty_line_is_not_a_heading(self):
        assert vd.heading_level("") is None

    def test_mid_line_hash_is_not_a_heading(self):
        assert vd.heading_level("some # text") is None


# ── validate_general ──────────────────────────────────────────────────────────


class TestValidateGeneral:
    def test_valid_single_h1_passes(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n## Section\n\nContent.\n")
        assert vd.ERRORS == []

    def test_missing_h1_raises_error(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "## Section only\n\nContent.\n")
        assert any("missing H1" in e for e in vd.ERRORS)

    def test_multiple_h1_raises_error(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# First\n\n# Second\n\n## Sub\n")
        assert any("multiple H1" in e for e in vd.ERRORS)

    def test_h5_heading_is_error(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n##### Too deep\n")
        assert any("H5" in e for e in vd.ERRORS)

    def test_h6_heading_is_error(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n###### Too deep\n")
        assert any("H6" in e for e in vd.ERRORS)

    def test_h4_is_allowed(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n#### H4 fine\n")
        assert vd.ERRORS == []

    def test_headings_inside_backtick_fence_ignored(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n```\n##### not real\n```\n")
        assert vd.ERRORS == []

    def test_headings_inside_tilde_fence_ignored(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_general(p, "# Title\n\n~~~\n##### not real\n~~~\n")
        assert vd.ERRORS == []


# ── validate_links ────────────────────────────────────────────────────────────


class TestValidateLinks:
    def test_external_https_link_skipped(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[GitHub](https://github.com)")
        assert vd.ERRORS == []

    def test_mailto_link_skipped(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[email](mailto:x@y.z)")
        assert vd.ERRORS == []

    def test_tel_link_skipped(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[call](tel:555-1234)")
        assert vd.ERRORS == []

    def test_anchor_only_link_skipped(self, tmp_path):
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[section](#my-section)")
        assert vd.ERRORS == []

    def test_broken_relative_link_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[missing](./nonexistent.md)")
        assert any("broken relative link" in e for e in vd.ERRORS)

    def test_valid_relative_link_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        (tmp_path / "other.md").write_text("# Other\n")
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[other](./other.md)")
        assert vd.ERRORS == []

    def test_relative_link_with_anchor_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        (tmp_path / "other.md").write_text("# Other\n")
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[sec](other.md#section)")
        assert vd.ERRORS == []

    def test_relative_link_with_query_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        (tmp_path / "other.md").write_text("# Other\n")
        p = tmp_path / "doc.md"
        vd.validate_links(p, "[sec](other.md?v=2)")
        assert vd.ERRORS == []

    def test_broken_link_outside_repo_is_error_not_traceback(
        self, tmp_path, monkeypatch
    ):
        """Regression for #957: `../../nope.md` from any nested doc resolves
        above ROOT and must produce one FAIL: line, not a ValueError from
        `Path.relative_to(ROOT)`."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        # Nesting once means `../../nope.md` resolves to the parent of tmp_path,
        # which is outside ROOT — that's the case that triggered the traceback.
        nested = tmp_path / "nested"
        nested.mkdir()
        p = nested / "doc.md"
        vd.validate_links(p, "[missing](../../nope.md)")
        assert len(vd.ERRORS) == 1
        assert "broken relative link '../../nope.md'" in vd.ERRORS[0]
        # The display path is shown absolutely because it lies outside ROOT.
        assert "/nope.md" in vd.ERRORS[0] or vd.ERRORS[0].endswith("nope.md")


# ── catalog frontmatter helpers ───────────────────────────────────────────────


def _catalog_frontmatter(name: str, entry_point: str, desc: str = "A skill") -> str:
    """Frontmatter satisfying validate_catalog_frontmatter().

    Every field in vd.CATALOG_FIELDS is required, `id` must equal `name`, and
    `entry_point` must be the file's own path relative to ROOT.
    """
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"id: {name}\n"
        "version: 1.0.0\n"
        "last_updated: 2026-01-01\n"
        f"one_line_purpose: {desc}\n"
        f"entry_point: {entry_point}\n"
        "category: meta\n"
        "status: active\n"
        "tags: [testing]\n"
        "---\n"
    )


def _write_router(tmp_path, name: str = "testsuite-docs") -> None:
    """Create the docs/SKILL.md router that validate_router() requires."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "SKILL.md").write_text(
        _catalog_frontmatter(name, "docs/SKILL.md", "Doc router") + "# Docs\n",
        encoding="utf-8",
    )


# ── validate_skill ────────────────────────────────────────────────────────────


class TestValidateSkill:
    def _skill(self, tmp_path, name, body="# Title\n", desc="A skill"):
        skill_dir = tmp_path / "docs" / "skills" / name
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text(
            _catalog_frontmatter(name, f"docs/skills/{name}/SKILL.md", desc) + body
        )
        return p

    def test_valid_skill_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._skill(tmp_path, "my-skill")
        vd.validate_skill(p)
        assert vd.ERRORS == []

    def test_missing_frontmatter_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        skill_dir = tmp_path / "docs" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text("# Title\nNo frontmatter")
        vd.validate_skill(p)
        assert any("missing YAML frontmatter" in e for e in vd.ERRORS)

    def test_missing_name_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        skill_dir = tmp_path / "docs" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text("---\ndescription: desc\n---\n# Title\n")
        vd.validate_skill(p)
        assert any("missing 'name'" in e for e in vd.ERRORS)

    def test_missing_description_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        skill_dir = tmp_path / "docs" / "skills" / "test"
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text("---\nname: test\n---\n# Title\n")
        vd.validate_skill(p)
        assert any("missing 'description'" in e for e in vd.ERRORS)

    def test_name_mismatch_with_directory_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._skill(tmp_path, "my-skill")
        # Overwrite with mismatching name
        p.write_text("---\nname: wrong-name\ndescription: desc\n---\n# Title\n")
        vd.validate_skill(p)
        assert any("does not match directory" in e for e in vd.ERRORS)

    def test_skill_md_over_500_lines_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._skill(tmp_path, "big-skill", body="# Title\n" + "line\n" * 500)
        vd.validate_skill(p)
        assert any("exceeds 500 lines" in e for e in vd.ERRORS)

    def test_reference_over_200_lines_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        ref_dir = tmp_path / "docs" / "skills" / "my-skill" / "references"
        ref_dir.mkdir(parents=True)
        p = ref_dir / "api.md"
        p.write_text("---\nname: api\ndescription: ref\n---\n# Title\n" + "line\n" * 200)
        vd.validate_skill(p)
        assert any("exceeds 200 lines" in e for e in vd.ERRORS)


# ── main() ────────────────────────────────────────────────────────────────────


class TestMain:
    def test_returns_0_on_clean_docs(self, tmp_path, monkeypatch):
        doc = tmp_path / "README.md"
        doc.write_text("# Title\n\nContent.\n")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [doc])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 0

    def test_returns_1_on_missing_h1(self, tmp_path, monkeypatch):
        doc = tmp_path / "bad.md"
        doc.write_text("## No H1 here\n")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [doc])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 1

    def test_returns_1_on_broken_link(self, tmp_path, monkeypatch):
        doc = tmp_path / "broken.md"
        doc.write_text("# Title\n\n[missing](./nope.md)\n")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [doc])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 1

    def test_non_skill_docs_validated_as_general(self, tmp_path, monkeypatch):
        """Files outside docs/skills/ go through validate_other (no frontmatter required)."""
        doc = tmp_path / "CONTRIBUTING.md"
        doc.write_text("# Contributing\n\nContent.\n")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [doc])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 0

    def test_skill_docs_require_frontmatter(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "docs" / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text("# Title\nNo frontmatter")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [p])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 1

    def test_empty_file_list_returns_0(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "collect_md_files", lambda: [])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        assert vd.main() == 0

    def test_missing_docs_skill_router_is_an_error(self, tmp_path, monkeypatch):
        """docs/SKILL.md is the factory onboarding entry point; absence must fail."""
        monkeypatch.setattr(vd, "collect_md_files", lambda: [])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        assert vd.main() == 1
        assert any("docs/SKILL.md is missing" in e for e in vd.ERRORS)

    def test_router_with_incomplete_catalog_frontmatter_is_an_error(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(vd, "collect_md_files", lambda: [])
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "SKILL.md").write_text("---\nname: docs\ndescription: d\n---\n# Docs\n")
        assert vd.main() == 1
        assert any("frontmatter missing 'entry_point'" in e for e in vd.ERRORS)


# ── validate_catalog_frontmatter: non-string category/status (#957) ──────────


class TestCatalogFrontmatterNonStringValues:
    """Direct exercise of validate_catalog_frontmatter().

    Most catalog rules are covered through TestValidateSkill; these tests
    pin the two crash paths called out by #957 — a list-valued `category`
    or `status` must produce a FAIL line, not a TypeError.
    """

    def _path(self, tmp_path, name="fake-skill"):
        p = tmp_path / "docs" / "skills" / name / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _fm(self, **overrides):
        base = {
            "name": "fake-skill",
            "description": "fake",
            "id": "fake-skill",
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "one_line_purpose": "fake",
            "entry_point": "docs/skills/fake-skill/SKILL.md",
            "category": "meta",
            "status": "active",
            "tags": ["testing"],
        }
        base.update(overrides)
        return base

    def test_list_valued_category_is_rejected_without_traceback(self, tmp_path, monkeypatch):
        """Regression for #957: `category: [meta]` must be a FAIL line, not a
        `TypeError: unhashable type: 'list'`."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._path(tmp_path)
        vd.validate_catalog_frontmatter(p, self._fm(category=["meta"]))
        assert len(vd.ERRORS) == 1
        assert "category must be one of" in vd.ERRORS[0]
        assert "['meta']" in vd.ERRORS[0]

    def test_list_valued_status_is_rejected_without_traceback(self, tmp_path, monkeypatch):
        """Regression for #957: `status: [active]` must be a FAIL line, not a
        `TypeError: unhashable type: 'list'`."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._path(tmp_path)
        vd.validate_catalog_frontmatter(p, self._fm(status=["active"]))
        assert len(vd.ERRORS) == 1
        assert "status must be one of" in vd.ERRORS[0]
        assert "['active']" in vd.ERRORS[0]

    def test_invalid_string_category_still_rejected(self, tmp_path, monkeypatch):
        """The pre-#957 behavior for an unknown string category is unchanged."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._path(tmp_path)
        vd.validate_catalog_frontmatter(p, self._fm(category="not-a-category"))
        assert any("category 'not-a-category' not in" in e for e in vd.ERRORS)

    def test_invalid_string_status_still_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._path(tmp_path)
        vd.validate_catalog_frontmatter(p, self._fm(status="pending"))
        assert any("status 'pending' not in" in e for e in vd.ERRORS)


# ── validate_catalog_frontmatter ──────────────────────────────────────────────


def _valid_catalog_fm(rel: str = "docs/skills/my-skill/SKILL.md") -> dict:
    """Parsed frontmatter that passes every validate_catalog_frontmatter rule."""
    return vd.parse_frontmatter(_catalog_frontmatter("my-skill", rel) + "# T\n")[0]


class TestValidateCatalogFrontmatter:
    REL = "docs/skills/my-skill/SKILL.md"

    def _check(self, tmp_path, monkeypatch, **overrides):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        fm = _valid_catalog_fm(self.REL)
        fm.update(overrides)
        vd.validate_catalog_frontmatter(tmp_path / self.REL, fm)
        return vd.ERRORS

    def test_valid_frontmatter_has_no_errors(self, tmp_path, monkeypatch):
        assert self._check(tmp_path, monkeypatch) == []

    @pytest.mark.parametrize("field", vd.CATALOG_FIELDS)
    def test_each_catalog_field_is_required(self, tmp_path, monkeypatch, field):
        errors = self._check(tmp_path, monkeypatch, **{field: None})
        assert any(f"frontmatter missing '{field}'" in e for e in errors)

    def test_unknown_category_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, category="misc")
        assert errors == [
            f"{tmp_path / self.REL}: category 'misc' not in {sorted(vd.CATEGORIES)}"
        ]

    @pytest.mark.parametrize("category", sorted(vd.CATEGORIES))
    def test_every_known_category_is_accepted(self, tmp_path, monkeypatch, category):
        assert self._check(tmp_path, monkeypatch, category=category) == []

    def test_unknown_status_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, status="draft")
        assert errors == [
            f"{tmp_path / self.REL}: status 'draft' not in {sorted(vd.STATUSES)}"
        ]

    @pytest.mark.parametrize("status", sorted(vd.STATUSES))
    def test_every_known_status_is_accepted(self, tmp_path, monkeypatch, status):
        assert self._check(tmp_path, monkeypatch, status=status) == []

    def test_id_differing_from_name_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, id="other-skill")
        assert errors == [
            f"{tmp_path / self.REL}: id 'other-skill' does not match name 'my-skill'"
        ]

    def test_id_without_name_is_not_compared(self, tmp_path, monkeypatch):
        assert self._check(tmp_path, monkeypatch, name=None, id="other") == []

    def test_entry_point_not_matching_own_path_is_error(self, tmp_path, monkeypatch):
        errors = self._check(
            tmp_path, monkeypatch, entry_point="docs/skills/other/SKILL.md"
        )
        assert errors == [
            f"{tmp_path / self.REL}: entry_point 'docs/skills/other/SKILL.md' "
            f"does not match its own path '{self.REL}'"
        ]

    def test_absolute_entry_point_is_error(
        self, tmp_path, monkeypatch
    ):
        errors = self._check(
            tmp_path, monkeypatch, entry_point=str(tmp_path / self.REL)
        )
        assert any("does not match its own path" in e for e in errors)

    @pytest.mark.parametrize(
        "value", ["2026-1-01", "01-01-2026", "2026/01/01", "2026-01-01T00:00", "today"]
    )
    def test_malformed_last_updated_is_error(self, tmp_path, monkeypatch, value):
        errors = self._check(tmp_path, monkeypatch, last_updated=value)
        assert errors == [
            f"{tmp_path / self.REL}: last_updated '{value}' is not YYYY-MM-DD"
        ]

    def test_yaml_date_last_updated_is_accepted(self, tmp_path, monkeypatch):
        """Unquoted YAML dates parse to datetime.date; str() must still match."""
        fm = _valid_catalog_fm(self.REL)
        assert not isinstance(fm["last_updated"], str)
        assert self._check(tmp_path, monkeypatch) == []

    def test_one_line_purpose_at_120_chars_is_accepted(self, tmp_path, monkeypatch):
        assert self._check(tmp_path, monkeypatch, one_line_purpose="x" * 120) == []

    def test_one_line_purpose_over_120_chars_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, one_line_purpose="x" * 121)
        assert errors == [
            f"{tmp_path / self.REL}: one_line_purpose exceeds 120 characters"
        ]

    def test_scalar_tags_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, tags="testing")
        assert errors == [f"{tmp_path / self.REL}: tags must be a non-empty list"]

    def test_empty_tags_list_is_error(self, tmp_path, monkeypatch):
        errors = self._check(tmp_path, monkeypatch, tags=[])
        assert f"{tmp_path / self.REL}: tags must be a non-empty list" in errors

    def test_skill_md_runs_catalog_rules(self, tmp_path, monkeypatch):
        """validate_skill() must route a skill's SKILL.md through the catalog schema."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        skill_dir = tmp_path / "docs" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        p = skill_dir / "SKILL.md"
        p.write_text(
            _catalog_frontmatter("my-skill", self.REL).replace(
                "status: active", "status: draft"
            )
            + "# T\n"
        )
        vd.validate_skill(p)
        assert any("status 'draft'" in e for e in vd.ERRORS)

    def test_skills_index_md_skips_catalog_rules(self, tmp_path, monkeypatch):
        """docs/skills/index.md is not a SKILL.md, so no catalog fields are required."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        skills = tmp_path / "docs" / "skills"
        skills.mkdir(parents=True)
        p = skills / "index.md"
        p.write_text("---\nname: skills\ndescription: index\n---\n# Skills\n")
        vd.validate_skill(p)
        assert vd.ERRORS == []


# ── reference frontmatter warnings ────────────────────────────────────────────


class TestReferenceNameWarning:
    def _ref(self, tmp_path, stem, name):
        ref_dir = tmp_path / "docs" / "skills" / "my-skill" / "references"
        ref_dir.mkdir(parents=True)
        p = ref_dir / f"{stem}.md"
        p.write_text(f"---\nname: {name}\ndescription: ref\n---\n# Ref\n")
        return p

    def test_name_mismatch_is_warning_not_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        p = self._ref(tmp_path, "api", "other")
        vd.validate_skill(p)
        assert vd.ERRORS == []
        assert vd.WARNINGS == [
            f"{p}: frontmatter name 'other' does not match filename 'api'"
        ]

    def test_matching_name_has_no_warning(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        vd.validate_skill(self._ref(tmp_path, "api", "api"))
        assert vd.ERRORS == [] and vd.WARNINGS == []

    def test_main_prints_warnings_and_still_passes(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        p = self._ref(tmp_path, "api", "other")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [p])
        assert vd.main() == 0
        out = capsys.readouterr().out
        assert "WARN: " in out and "does not match filename 'api'" in out
        assert "All docs validation checks passed." in out


# ── validate_router / main dispatch ───────────────────────────────────────────


class TestRouterAndDispatch:
    def test_router_without_frontmatter_is_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SKILL.md").write_text("# Docs\n")
        vd.validate_router()
        assert vd.ERRORS == ["docs/SKILL.md: missing YAML frontmatter"]

    def test_router_entry_point_must_be_docs_skill_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "SKILL.md").write_text(
            _catalog_frontmatter("testsuite-docs", "docs/index.md") + "# Docs\n"
        )
        vd.validate_router()
        assert any("does not match its own path 'docs/SKILL.md'" in e for e in vd.ERRORS)

    def test_router_is_validated_as_general_doc_not_as_skill(
        self, tmp_path, monkeypatch
    ):
        """docs/SKILL.md's parent is 'docs', so the name-vs-directory rule must not fire."""
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path, name="not-docs")
        router = tmp_path / "docs" / "SKILL.md"
        monkeypatch.setattr(vd, "collect_md_files", lambda: [router])
        assert vd.main() == 0
        assert vd.ERRORS == []

    def test_main_prints_each_failure(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        _write_router(tmp_path)
        doc = tmp_path / "bad.md"
        doc.write_text("no heading\n##### too deep\n")
        monkeypatch.setattr(vd, "collect_md_files", lambda: [doc])
        assert vd.main() == 1
        out = capsys.readouterr().out
        assert f"FAIL: {doc}:2: H5 heading (max H4)" in out
        assert f"FAIL: {doc}: missing H1" in out
        assert "All docs validation checks passed." not in out


# ── collect_md_files ──────────────────────────────────────────────────────────


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )


class TestCollectMdFiles:
    @pytest.fixture
    def no_parent_repo(self, tmp_path, monkeypatch):
        """Stop git discovering a repository above tmp_path."""
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        return tmp_path

    @pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
    def test_git_repo_returns_only_tracked_md_sorted(self, no_parent_repo):
        root = no_parent_repo
        _git(root, "init", "-q")
        (root / "docs").mkdir()
        (root / "z.md").write_text("# Z\n")
        (root / "docs" / "a.md").write_text("# A\n")
        (root / "notes.txt").write_text("not markdown\n")
        _git(root, "add", "z.md", "docs/a.md", "notes.txt")
        (root / "untracked.md").write_text("# U\n")

        assert vd.collect_md_files() == [root / "docs" / "a.md", root / "z.md"]

    @pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
    def test_non_git_directory_falls_back_to_filtered_walk(self, no_parent_repo):
        root = no_parent_repo
        keep = [root / "README.md", root / "docs" / "guide.md"]
        skip = [
            root / "node_modules" / "pkg" / "README.md",
            root / "__pycache__" / "x.md",
            root / ".venv" / "lib" / "x.md",
            root / ".worktrees" / "branch" / "README.md",
            root / ".git" / "x.md",
            root / ".github" / "ISSUE_TEMPLATE" / "bug.md",
        ]
        for p in keep + skip:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# T\n")

        assert vd.collect_md_files() == sorted(keep)

    def test_missing_git_binary_falls_back_to_walk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vd, "ROOT", tmp_path)
        (tmp_path / "README.md").write_text("# T\n")

        def no_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", no_git)
        assert vd.collect_md_files() == [tmp_path / "README.md"]
