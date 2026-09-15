"""Unit tests for the image-slug grammar owned by scripts/image_slug.py.

These pin the contract that the E2E screenshot publisher and its two consumers
(the boot-time summary heading and the gh-pages URL builder) now share.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.image_slug import image_slug, main, split_image_slug  # noqa: E402


# Every slug the dashboard currently ingests must keep its exact spelling, or
# published GHCR tags move and the gh-pages screenshots 404.
@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("ghcr.io/projectbluefin/bluefin:testing", "bluefin-testing"),
        ("ghcr.io/projectbluefin/bluefin-lts:testing", "bluefin-lts-testing"),
        ("ghcr.io/projectbluefin/dakota:testing", "dakota-testing"),
    ],
)
def test_published_slugs_are_unchanged(ref, expected):
    assert image_slug(ref) == expected


def test_digest_pinned_ref_folds_the_at_sign():
    # The old consumers left '@' in place and produced a URL that 404s.
    assert (
        image_slug("ghcr.io/projectbluefin/bluefin@sha256:abc123")
        == "bluefin-sha256-abc123"
    )


def test_non_ghcr_registry_is_stripped():
    # The old publisher's sed only matched ghcr.io and left slashes in the tag.
    assert image_slug("quay.io/fedora-ostree-desktops/silverblue:44") == "silverblue-44"


def test_nested_image_path_keeps_the_group_segment():
    # The old consumers dropped the group, collapsing two images onto one slug.
    assert image_slug("ghcr.io/projectbluefin/bluefin/dx:latest") == "bluefin-dx-latest"


def test_composed_e2e_image_ref():
    assert image_slug("ghcr.io/projectbluefin/testsuite-e2e:run-123") == (
        "testsuite-e2e-run-123"
    )


def test_bare_name_without_registry_or_org():
    assert image_slug("bluefin:testing") == "bluefin-testing"


def test_localhost_registry_is_treated_as_a_host():
    assert image_slug("localhost:5000/org/bluefin:testing") == "bluefin-testing"


@pytest.mark.parametrize("ref", ["", "   ", None, "/", "///"])
def test_empty_refs_fall_back_instead_of_emitting_an_empty_tag(ref):
    assert image_slug(ref) == "unknown-image"


def test_result_is_always_a_legal_oci_tag():
    slug = image_slug("ghcr.io/org/we!rd$name@sha256:" + "f" * 200)
    assert len(slug) <= 128
    assert slug[0].isalnum()
    assert not slug.endswith(("-", "."))
    assert all(char.isalnum() or char in "._-" for char in slug)


def test_cli_prints_the_slug(capsys):
    assert main(["ghcr.io/projectbluefin/bluefin:testing"]) == 0
    assert capsys.readouterr().out.strip() == "bluefin-testing"


def test_cli_is_executable_as_a_script():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "image_slug.py"),
            "ghcr.io/projectbluefin/dakota:testing",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "dakota-testing"


# ── Inverse grammar (consumed by dashboard/scripts/convert_behave.py) ────────


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("bluefin-testing", ("bluefin", "testing")),
        ("bluefin-lts-testing", ("bluefin-lts", "testing")),
        ("dakota-testing", ("dakota", "testing")),
        ("bluefin-stable", ("bluefin", "stable")),
        ("bluefin-lts", ("bluefin", "lts")),
    ],
)
def test_split_image_slug_matches_the_previous_dashboard_behaviour(slug, expected):
    assert split_image_slug(slug) == expected


def test_split_image_slug_does_not_amputate_an_unknown_trailing_segment():
    # The old dashboard split turned this into ('bluefin-sha256', 'abc123').
    assert split_image_slug("bluefin-sha256-abc123") == (
        "bluefin-sha256-abc123",
        "testing",
    )


def test_split_image_slug_handles_a_flavor_with_no_separator():
    assert split_image_slug("bluefin") == ("bluefin", "testing")


@pytest.mark.parametrize("slug", ["", "   ", None])
def test_split_image_slug_falls_back_on_empty_input(slug):
    assert split_image_slug(slug) == ("unknown-image", "testing")


def test_round_trip_from_ref_to_flavor_and_stream():
    flavor, stream = split_image_slug(
        image_slug("ghcr.io/projectbluefin/bluefin-lts:testing")
    )
    assert (flavor, stream) == ("bluefin-lts", "testing")


def test_dashboard_converter_consumes_the_shared_split(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "dashboard" / "scripts"))
    from convert_behave import convert_behave_json  # noqa: E402

    behave_json = tmp_path / "results.json"
    behave_json.write_text(
        json.dumps(
            [
                {
                    "name": "Smoke",
                    "elements": [
                        {
                            "type": "scenario",
                            "name": "System boots",
                            "status": "passed",
                            "steps": [{"result": {"status": "passed", "duration": 1.0}}],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    run = convert_behave_json(
        str(behave_json),
        run_id="123",
        caller_repo="projectbluefin/testsuite",
        slug="bluefin-lts-testing",
        suite="smoke",
        timestamp="2026-01-01T00:00:00Z",
    )
    assert run is not None
    assert run["flavor"] == "bluefin-lts"
    assert run["stream"] == "testing"
