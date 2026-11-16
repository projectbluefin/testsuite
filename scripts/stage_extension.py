#!/usr/bin/env python3
"""Validate one packaged extension ZIP and stage it into a guest before boot.

The extension-validation lane (#909) must test the exact archive the builder
produced, installed where GNOME Shell discovers it at session start, and must
never blame an extension that was not actually installed. This runs on the
runner host, as root, against the mounted guest disk, before the VM boots:

1. The archive's SHA256 must equal the hash the builder recorded.
2. The archive names its own UUID; it must be one of the canonical contracts
   in ``tests/shared/gnome_extensions_artifacts.py`` and pass that contract's
   member, metadata and required-path checks. Nothing is extracted before that.
3. Its members are written into the desktop user's
   ``~/.local/share/gnome-shell/extensions/<uuid>/``, owned by that user. The
   target must not exist yet (each extension gets a fresh guest), and no
   existing path component may be a symlink.

On success it writes a provenance record naming the contract, the collection
profile and the Behave tag that selects the extension's scenarios. On failure
it writes ``{"staged": false, "category": ..., "error": ...}`` and exits 1;
``category`` is ``harness``, ``metadata`` or ``artifact`` as in the validator.
Standard library only.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.shared import gnome_extensions_artifacts as art  # noqa: E402

COLLECTION = Path(__file__).resolve().parents[1] / "tests" / "extensions" / "collection.json"
EXTENSIONS_SUBDIR = Path(".local/share/gnome-shell/extensions")
GUEST_HOME = "/var/home/bluefin-test"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TAG = re.compile(r"^[a-z0-9_]+$")


class StagingError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def profile_for(uuid: str, collection_path: Path = COLLECTION) -> tuple[str, dict]:
    """The collection profile (key and entry) that tests ``uuid``."""
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    for key, entry in collection.items():
        if entry.get("uuid") == uuid:
            if not _TAG.fullmatch(entry.get("tag", "")):
                raise StagingError(art.CATEGORY_HARNESS, f"profile {key} has no usable Behave tag")
            return key, entry
    raise StagingError(art.CATEGORY_HARNESS, f"no collection profile tests {uuid}")


def validate(zip_path: Path, sha256: str) -> art.ExtensionContract:
    """Check hash, UUID and contract before anything is extracted."""
    if not zip_path.is_file():
        raise StagingError(art.CATEGORY_HARNESS, f"no extension ZIP at {str(zip_path)!r}")
    sha256 = sha256.strip().lower()
    if not _SHA256.fullmatch(sha256):
        raise StagingError(art.CATEGORY_HARNESS, f"builder SHA256 is not a hex digest: {sha256!r}")
    actual = art._sha256_zip(zip_path)
    if actual != sha256:
        raise StagingError(art.CATEGORY_ARTIFACT, f"SHA256 mismatch: builder recorded {sha256}, archive is {actual}")
    try:
        uuid = art.read_archive_uuid(zip_path)
    except art.ArtifactValidationError as exc:
        raise StagingError(exc.category, str(exc)) from exc
    contract = art.find_contract(uuid)
    if contract is None:
        raise StagingError(art.CATEGORY_METADATA, f"archive declares {uuid!r}, which has no canonical contract")
    pinned = dataclasses.replace(contract, zip_sha256=sha256)
    try:
        result = art.validate_extension_zip(zip_path, pinned)
    except art.ArtifactValidationError as exc:
        raise StagingError(exc.category, str(exc)) from exc
    if not result.valid:
        raise StagingError(art.classify(result), "; ".join(result.errors))
    return pinned


def _make_dirs(home: Path, relative: Path, uid: int, gid: int, chown) -> Path:
    """Create ``home/relative`` one component at a time, refusing symlinks."""
    if home.is_symlink() or not home.is_dir():
        raise StagingError(art.CATEGORY_HARNESS, f"desktop home {home} is missing or a symlink")
    current = home
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise StagingError(art.CATEGORY_HARNESS, f"refusing symlink in staging path: {current}")
        if not current.exists():
            current.mkdir(mode=0o755)
            chown(current, uid, gid)
        elif not current.is_dir():
            raise StagingError(art.CATEGORY_HARNESS, f"staging path component is not a directory: {current}")
    return current


def extract(zip_path: Path, target: Path, uid: int, gid: int, chown=os.chown) -> int:
    """Write the validated members into ``target``; return the file count."""
    if target.exists() or target.is_symlink():
        raise StagingError(art.CATEGORY_HARNESS, f"{target} already exists; the guest is not fresh")
    target.mkdir(mode=0o755)
    chown(target, uid, gid)
    files = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.rstrip("/")
            parent = _make_dirs(target, Path(name).parent, uid, gid, chown) if "/" in name else target
            if info.is_dir():
                _make_dirs(target, Path(name), uid, gid, chown)
                continue
            mode = (info.external_attr >> 16) if info.create_system == 3 else 0
            perm = 0o755 if mode & stat.S_IXUSR else 0o644
            path = parent / Path(name).name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, perm)
            with os.fdopen(fd, "wb") as out, zf.open(info) as src:
                while chunk := src.read(1 << 16):
                    out.write(chunk)
            os.chmod(path, perm)
            chown(path, uid, gid)
            files += 1
    return files


def stage(zip_path: Path, sha256: str, home: Path, uid: int, gid: int,
          guest_home: str = GUEST_HOME, collection_path: Path = COLLECTION, chown=os.chown) -> dict:
    contract = validate(zip_path, sha256)
    key, profile = profile_for(contract.uuid, collection_path)
    extensions = _make_dirs(home, EXTENSIONS_SUBDIR, uid, gid, chown)
    files = extract(zip_path, extensions / contract.uuid, uid, gid, chown)
    return {
        "staged": True,
        "uuid": contract.uuid,
        "profile": key,
        "tag": profile["tag"],
        "source_repo": contract.source_repo,
        "source_rev": contract.source_rev,
        "package_recipe": contract.package_recipe,
        "zip_sha256": contract.zip_sha256,
        "files": files,
        "guest_path": f"{guest_home}/{EXTENSIONS_SUBDIR}/{contract.uuid}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip", type=Path, help="packaged extension ZIP")
    parser.add_argument("--sha256", required=True, help="hash the builder recorded")
    parser.add_argument("--home", type=Path, required=True, help="desktop user's home on the mounted guest disk")
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True, help="provenance JSON to write")
    args = parser.parse_args(argv)
    try:
        report = stage(args.zip, args.sha256, args.home, args.uid, args.gid)
        rc = 0
    except StagingError as exc:
        report = {"staged": False, "category": exc.category, "error": str(exc)}
        print(f"::error::extension staging failed ({exc.category}): {exc}", file=sys.stderr)
        rc = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
