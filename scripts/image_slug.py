#!/usr/bin/env python3
"""Canonical image-slug grammar for testsuite screenshot and dashboard naming.

Derives a stable, valid OCI tag slug from an OCI container image reference.
Strips registry host and org/namespace, folds remaining '/', ':', and '@' into '-',
and sanitizes to the OCI tag charset ([a-zA-Z0-9_.-]).
"""

import os
import re
import sys


def get_image_slug(image_ref: str, fallback: str = "bluefin-testing") -> str:
    """Derive an image slug from an OCI container reference.

    Rules:
    - If empty or None, returns fallback (default: 'bluefin-testing').
    - Strip registry host if present (domain containing '.' or ':', or 'localhost').
    - Strip organization / namespace if present (first path component after host, or first path component if no host).
    - Fold remaining '/', ':', and '@' separators into '-'.
    - Sanitize any remaining characters to the OCI tag charset ([a-zA-Z0-9_.-]).
    - Strip leading '.' and '-' characters to conform with OCI tag grammar.
    - If sanitized slug is empty, returns fallback.
    - Truncate to maximum 128 characters (OCI tag limit).
    """
    image_ref = (image_ref or "").strip()
    if not image_ref:
        return fallback

    parts = image_ref.split("/")
    # Detect and strip registry host if present
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        parts.pop(0)

    # Strip organization/namespace if present
    if len(parts) > 1:
        parts.pop(0)

    remainder = "/".join(parts)
    # Fold remaining '/', ':', '@' into '-'
    slug = re.sub(r"[/:\@]", "-", remainder)
    # Sanitize characters outside OCI tag charset [a-zA-Z0-9_.-]
    slug = re.sub(r"[^a-zA-Z0-9_.-]", "-", slug)
    # OCI tags may not start with '.' or '-'
    slug = slug.lstrip(".-")
    if not slug:
        return fallback
    if len(slug) > 128:
        slug = slug[:128].rstrip(".-")
    return slug


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        ref = argv[0]
    elif not sys.stdin.isatty():
        content = sys.stdin.read().strip()
        ref = content if content else os.environ.get("BASE_IMAGE", "")
    else:
        ref = os.environ.get("BASE_IMAGE", "")
    print(get_image_slug(ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
