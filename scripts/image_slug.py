#!/usr/bin/env python3
"""Single owner of the image-slug grammar used by the E2E screenshot pipeline.

The "image slug" is the identity string that names a tested image inside the
screenshot / QA-dashboard pipeline. It is embedded in the GHCR artifact tag
pushed by ``.github/workflows/e2e.yml``::

    ghcr.io/projectbluefin/testsuite/desktop-screenshot:<slug>-<suite>-latest

and in the gh-pages URL rendered into the job summary. Before this module the
grammar was restated three times in ``e2e.yml`` with three different
implementations that agreed only for ``ghcr.io/<org>/<name>:<tag>`` refs and
diverged on digest-pinned refs, non-GHCR registries and nested image paths.

Grammar: drop the registry host and the org/user segment, then fold every
remaining ``/``, ``:`` and ``@`` into ``-`` and sanitize to the OCI tag
charset. This reproduces the previously-published slug byte-for-byte for every
``ghcr.io/<org>/<name>:<tag>`` input, so no existing tag moves.

:func:`split_image_slug` is the inverse used by the dashboard converter, which
previously restated its own lossy version of it.
"""

from __future__ import annotations

import argparse
import re
import sys

# OCI tags: [A-Za-z0-9_][A-Za-z0-9._-]{0,127}
_TAG_ILLEGAL = re.compile(r"[^A-Za-z0-9._-]")
_MAX_TAG_LENGTH = 128
_FALLBACK_SLUG = "unknown-image"

# Image streams the fleet publishes. Used to split a slug back into
# (flavor, stream) without guessing that the last '-' segment is a stream.
KNOWN_STREAMS = frozenset({"testing", "stable", "latest", "lts", "gts", "beta"})
DEFAULT_STREAM = "testing"


def _is_registry_host(segment: str) -> bool:
    """Return True if ``segment`` is a registry host rather than a path part.

    Docker's own rule: the first segment is a registry only when it contains a
    ``.`` or a ``:``, or is exactly ``localhost``.
    """
    return "." in segment or ":" in segment or segment == "localhost"


def image_slug(image_ref: str) -> str:
    """Derive the canonical slug for ``image_ref``.

    >>> image_slug("ghcr.io/projectbluefin/bluefin:testing")
    'bluefin-testing'
    >>> image_slug("ghcr.io/projectbluefin/bluefin@sha256:abc123")
    'bluefin-sha256-abc123'
    >>> image_slug("quay.io/fedora-ostree-desktops/silverblue:44")
    'silverblue-44'
    """
    ref = (image_ref or "").strip().strip("/")
    if not ref:
        return _FALLBACK_SLUG

    segments = ref.split("/")
    if len(segments) > 1 and _is_registry_host(segments[0]):
        segments = segments[1:]
    # Drop the org/user segment, but never the final name-bearing segment.
    if len(segments) > 1:
        segments = segments[1:]

    slug = _TAG_ILLEGAL.sub("-", "-".join(segments))
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    slug = slug[:_MAX_TAG_LENGTH].rstrip("-.")
    return slug or _FALLBACK_SLUG


def split_image_slug(slug: str) -> tuple[str, str]:
    """Split a slug back into its ``(flavor, stream)`` pair.

    This is the inverse of :func:`image_slug` and is what the dashboard needs in
    order to group runs. The slug is lossy — ``-`` is both the flavor's own
    separator and the flavor/stream separator — so the split is only sound for
    slugs whose trailing segment is a known stream. Anything else is reported as
    flavor-only with the default stream, rather than silently amputating the
    last segment of the flavor.

    >>> split_image_slug("bluefin-lts-testing")
    ('bluefin-lts', 'testing')
    >>> split_image_slug("bluefin-sha256-abc123")
    ('bluefin-sha256-abc123', 'testing')
    """
    slug = (slug or "").strip()
    if not slug:
        return _FALLBACK_SLUG, DEFAULT_STREAM

    flavor, separator, trailing = slug.rpartition("-")
    if separator and flavor and trailing in KNOWN_STREAMS:
        return flavor, trailing
    return slug, DEFAULT_STREAM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image_ref", help="Full image reference, e.g. ghcr.io/org/name:tag")
    args = parser.parse_args(argv)
    print(image_slug(args.image_ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
