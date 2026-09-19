"""Unit tests for the canonical image-slug grammar (scripts/image_slug.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.image_slug import get_image_slug

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "image_slug.py"


def test_standard_ghcr_tagged():
    assert get_image_slug("ghcr.io/projectbluefin/bluefin:testing") == "bluefin-testing"
    assert get_image_slug("ghcr.io/projectbluefin/dakota:latest") == "dakota-latest"
    assert get_image_slug("ghcr.io/ublue-os/bluefin:stable") == "bluefin-stable"


def test_standard_ghcr_untagged():
    assert get_image_slug("ghcr.io/projectbluefin/bluefin-testing") == "bluefin-testing"
    assert get_image_slug("ghcr.io/projectbluefin/bluefin-lts-testing") == "bluefin-lts-testing"
    assert get_image_slug("ghcr.io/projectbluefin/dakota-testing") == "dakota-testing"


def test_digest_pinned_ref():
    digest = "72166e4407b8b704c7c6a96e8324f8d2ccf04494a8cbf5e5c9a752254308a342"
    ref = f"ghcr.io/projectbluefin/bluefin@sha256:{digest}"
    expected = f"bluefin-sha256-{digest}"
    assert get_image_slug(ref) == expected


def test_non_ghcr_bases():
    assert get_image_slug("quay.io/fedora-ostree-desktops/silverblue:44") == "silverblue-44"
    assert get_image_slug("quay.io/silverblue:44") == "silverblue-44"


def test_nested_image_paths():
    assert (
        get_image_slug("ghcr.io/projectbluefin/subgroup/bluefin:latest")
        == "subgroup-bluefin-latest"
    )
    assert (
        get_image_slug("ghcr.io/projectbluefin/a/b/c:tag")
        == "a-b-c-tag"
    )


def test_docker_hub_references():
    assert get_image_slug("docker.io/library/ubuntu:22.04") == "ubuntu-22.04"
    assert get_image_slug("docker.io/projectbluefin/bluefin:stable") == "bluefin-stable"


def test_local_registry_with_port():
    assert (
        get_image_slug("localhost:5000/projectbluefin/bluefin:latest")
        == "bluefin-latest"
    )
    assert get_image_slug("127.0.0.1:5000/org/image:v1") == "image-v1"


def test_bare_and_no_host_references():
    assert get_image_slug("projectbluefin/bluefin:latest") == "bluefin-latest"
    assert get_image_slug("bluefin:latest") == "bluefin-latest"
    assert get_image_slug("bluefin") == "bluefin"


def test_empty_and_fallback():
    assert get_image_slug("") == "bluefin-testing"
    assert get_image_slug("   ") == "bluefin-testing"
    assert get_image_slug(None) == "bluefin-testing"  # type: ignore[arg-type]
    assert get_image_slug("", fallback="custom-fallback") == "custom-fallback"


def test_sanitizes_oci_charset():
    # Disallowed chars like $, #, +, % should be replaced with -
    assert get_image_slug("ghcr.io/org/app+name:v1$2") == "app-name-v1-2"
    # Leading dots and dashes must be stripped
    assert get_image_slug("ghcr.io/org/.--app:v1") == "app-v1"


def test_oci_tag_length_limit():
    long_name = "a" * 150
    slug = get_image_slug(f"ghcr.io/org/{long_name}:tag")
    assert len(slug) <= 128
    assert not slug.endswith("-")
    assert not slug.endswith(".")


def test_byte_identical_to_legacy_site2_on_published_slugs():
    """Verify byte-identity with legacy e2e.yml site 2 for all currently published slugs."""
    published_refs = [
        "ghcr.io/projectbluefin/bluefin-testing",
        "ghcr.io/projectbluefin/bluefin:testing",
        "ghcr.io/projectbluefin/bluefin-lts-testing",
        "ghcr.io/projectbluefin/dakota-testing",
        "ghcr.io/projectbluefin/dakota:latest",
        "ghcr.io/projectbluefin/bluefin@sha256:1234567890abcdef",
    ]
    for ref in published_refs:
        # Legacy site 2: sed 's|ghcr.io/[^/]*/||' | tr ':@' '--'
        legacy = (
            subprocess.check_output(
                f"echo '{ref}' | sed 's|ghcr.io/[^/]*/||' | tr ':@' '--'",
                shell=True,
                text=True,
            ).strip()
        )
        assert get_image_slug(ref) == legacy


def test_cli_invocation_argv():
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "ghcr.io/projectbluefin/bluefin:testing"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "bluefin-testing"


def test_cli_invocation_stdin():
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input="quay.io/fedora-ostree-desktops/silverblue:44\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "silverblue-44"


def test_cli_invocation_env():
    env = os.environ.copy()
    env["BASE_IMAGE"] = "ghcr.io/projectbluefin/subgroup/bluefin:latest"
    res = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "subgroup-bluefin-latest"


def test_sparse_checkout_includes_image_slug():
    workflow_content = (REPO_ROOT / ".github" / "workflows" / "e2e.yml").read_text()
    assert "scripts/image_slug.py" in workflow_content
