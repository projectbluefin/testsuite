"""Unit tests for scripts/validate_docs.py."""

from __future__ import annotations

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


# ── validate_catalog_frontmatter (direct) ────────────────────────────────────


class TestValidateCatalogFrontmatter:
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
