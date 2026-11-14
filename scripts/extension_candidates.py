#!/usr/bin/env python3
"""Plan, validate and stage candidate GNOME Shell extensions for a guest.

Issue #909 step 2: the exact candidate package must be in the desktop user's
extension directory before GNOME Shell first starts, and nothing in the suite
installs it. The ``gnome-e2e`` action runs ``stage`` on the runner, as root,
against the ostree stateroot it just installed and before the VM boots, in the
same place ``scripts/guest_accounts.py`` sets up the isolated accounts (#908
Option A).

Subcommands:

* ``plan PROFILE`` prints the pinned source coordinates for one profile in
  ``tests/extensions/collection.json`` as ``key=value`` lines for
  ``$GITHUB_OUTPUT``. The revision comes from the canonical contract in
  ``tests/shared/gnome_extensions_artifacts.py``, so there is one pin.
* ``compare ZIP ZIP`` reports whether two builds of the same revision are
  byte-identical and, if not, whether only archive metadata (timestamps,
  order) differs. A ``zip_sha256`` pin is only meaningful for a recipe whose
  rebuilds are byte-identical.
* ``validate ZIP...`` checks each archive against the contract its own
  ``metadata.json`` names, without extracting anything.
* ``stage --home HOME ZIP...`` validates the same way, then extracts each
  archive's regular files into ``HOME/.local/share/gnome-shell/extensions/
  <uuid>/``, owned by the desktop user. It writes a provenance report and the
  Behave tag selection for the staged profiles.

Candidates go into the desktop user's own extension directory, never a system
path: only that account's session loads them, the harness account never does,
and the helper fault-injection scenarios need to replace files in the
installed package. Schemas are compiled later, in the guest, as the desktop
user (as ``gnome-extensions install`` does), so the guest's own GLib builds
them.

See ``docs/skills/ci-ops/e2e-workflow/references/gnome-extensions-validation.md``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.shared import gnome_extensions_artifacts as artifacts

COLLECTION = ROOT / "tests" / "extensions" / "collection.json"
EXTENSIONS_SUBDIR = (".local", "share", "gnome-shell", "extensions")
GUEST_HOME = "/var/home/bluefin-test"
#: Upper bound on the total uncompressed size staged from one archive. The
#: largest hive candidate is well under 5 MiB; anything larger is refused
#: before it fills the guest disk.
MAX_STAGED_BYTES = 64 << 20
_TAG = re.compile(r"^[a-z0-9_]+$")
_REV = re.compile(r"^[0-9a-f]{40}$")
#: The harness puts staged UUIDs into guest shell commands and paths.
_UUID = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$")


class CandidateError(RuntimeError):
    """A candidate cannot be planned, validated or staged."""


def load_collection(path: Path = COLLECTION) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def profile_for_uuid(collection: dict, uuid: str) -> tuple[str, dict]:
    for name, profile in collection.items():
        if profile.get("uuid") == uuid:
            return name, profile
    raise CandidateError(f"{uuid} is not in the extension collection")


def plan(profile_name: str, collection: dict | None = None) -> dict[str, str]:
    """Source coordinates for one profile, from the collection and its contract."""
    collection = load_collection() if collection is None else collection
    profile = collection.get(profile_name)
    if profile is None:
        raise CandidateError(f"unknown extension profile: {profile_name}")
    contract = artifacts.find_contract(profile["uuid"])
    if contract is None:
        raise CandidateError(f"{profile['uuid']} has no canonical contract")
    if contract.source_repo != profile.get("repository"):
        raise CandidateError(
            f"collection repository {profile.get('repository')} does not match "
            f"contract {contract.source_repo}"
        )
    if not _REV.match(contract.source_rev):
        raise CandidateError(f"contract revision is not a full SHA: {contract.source_rev}")
    command = profile.get("package_command")
    if not command:
        raise CandidateError(
            f"profile {profile_name} has no packaging recipe the lane can run yet"
        )
    tag = profile.get("tag", "")
    if not _TAG.match(tag):
        raise CandidateError(f"profile {profile_name} has an unusable tag: {tag!r}")
    return {
        "profile": profile_name,
        "uuid": contract.uuid,
        "repository": contract.source_repo,
        "revision": contract.source_rev,
        "package_command": command,
        "package_recipe": contract.package_recipe,
        "tag": tag,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(paths: list[Path], collection: dict | None = None) -> list[dict]:
    """Validate each archive against its contract; raise on the first failure.

    The archive names its own contract through ``metadata.json`` (as
    ``gnome_extensions_artifacts.main`` does), each UUID may appear once, and
    every UUID must also be a collection profile, so a staged extension always
    has scenarios to run.
    """
    collection = load_collection() if collection is None else collection
    if not paths:
        raise CandidateError("no candidate archives given")
    seen: set[str] = set()
    records = []
    for path in paths:
        try:
            uuid = artifacts.read_archive_uuid(path)
        except artifacts.ArtifactValidationError as exc:
            raise CandidateError(f"{path}: [{exc.category}] {exc}") from exc
        if not _UUID.match(uuid):
            raise CandidateError(f"{path}: unusable uuid {uuid!r}")
        if uuid in seen:
            raise CandidateError(f"{uuid} staged twice")
        seen.add(uuid)
        contract = artifacts.find_contract(uuid)
        if contract is None:
            raise CandidateError(f"{path}: {uuid} has no canonical contract")
        name, profile = profile_for_uuid(collection, uuid)
        result = artifacts.validate_extension_zip(path, contract)
        if not result.valid:
            raise CandidateError(
                f"{path}: [{artifacts.classify(result)}] " + "; ".join(result.errors)
            )
        tag = profile.get("tag", "")
        if not _TAG.match(tag):
            raise CandidateError(f"profile {name} has an unusable tag: {tag!r}")
        records.append({
            "profile": name,
            "uuid": uuid,
            "tag": tag,
            "source_repo": contract.source_repo,
            "source_rev": contract.source_rev,
            "package_recipe": contract.package_recipe,
            "zip_sha256": _sha256(path),
            "pinned_zip_sha256": contract.zip_sha256,
            "archive": path.name,
        })
    return records


def _members(path: Path) -> dict[str, tuple[int, int]]:
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: (info.CRC, info.file_size)
            for info in archive.infolist() if not info.is_dir()
        }


def compare(first: Path, second: Path) -> dict:
    """Reproducibility report for two archives built from one revision."""
    a, b = _members(first), _members(second)
    differing = sorted(name for name in a.keys() | b.keys() if a.get(name) != b.get(name))
    sha_a, sha_b = _sha256(first), _sha256(second)
    return {
        "sha256": [sha_a, sha_b],
        "byte_identical": sha_a == sha_b,
        "content_identical": not differing,
        "differing_members": differing,
    }


def _refuse_link(path: Path) -> None:
    # Root writes into a guest tree: never follow a link out of it.
    if path.is_symlink():
        raise CandidateError(f"{path} is a symlink; refusing to write through it")


def _make_dir(path: Path, uid: int, gid: int, chown) -> None:
    _refuse_link(path)
    if path.exists():
        if not path.is_dir():
            raise CandidateError(f"{path} exists and is not a directory")
        return
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    chown(path, uid, gid)


def extract(zip_path: Path, dest: Path, uid: int, gid: int, chown=os.lchown) -> int:
    """Extract the archive's regular files into a new ``dest``; return the count.

    ``validate`` has already rejected unsafe names, links and special members.
    ``dest`` must not exist yet, files are created exclusively without
    following links, and the total size is capped, so nothing outside ``dest``
    is written and a stale or planted tree is never merged into.
    """
    _refuse_link(dest)
    if os.path.lexists(dest):
        raise CandidateError(f"{dest} already exists; refusing to stage over it")
    dest.mkdir(mode=0o755)
    dest.chmod(0o755)
    chown(dest, uid, gid)
    written = 0
    count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            parts = info.filename.rstrip("/").split("/")
            current = dest
            for part in parts[:-1] if not info.is_dir() else parts:
                current = current / part
                _make_dir(current, uid, gid, chown)
            if info.is_dir():
                continue
            target = current / parts[-1]
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "wb") as out, archive.open(info) as source:
                for chunk in iter(lambda: source.read(1 << 16), b""):
                    written += len(chunk)
                    if written > MAX_STAGED_BYTES:
                        raise CandidateError(
                            f"{zip_path} expands past {MAX_STAGED_BYTES} bytes"
                        )
                    out.write(chunk)
            os.chmod(target, 0o644)
            chown(target, uid, gid)
            count += 1
    return count


def behave_tags(records: list[dict]) -> str:
    """Behave tag expression selecting the staged profiles' scenarios."""
    return " or ".join(f"@{tag}" for tag in sorted({r["tag"] for r in records}))


def stage(home: Path, paths: list[Path], uid: int, gid: int, chown=os.lchown,
          collection: dict | None = None) -> list[dict]:
    """Validate every archive, then stage each into the desktop user's home."""
    records = validate(paths, collection)
    if not home.is_dir() or home.is_symlink():
        raise CandidateError(f"desktop home {home} is missing or a symlink")
    current = home
    for part in EXTENSIONS_SUBDIR:
        current = current / part
        _make_dir(current, uid, gid, chown)
    by_uuid = {r["uuid"]: r for r in records}
    for path in paths:
        uuid = artifacts.read_archive_uuid(path)
        record = by_uuid[uuid]
        dest = current / uuid
        record["files"] = extract(path, dest, uid, gid, chown)
        record["staged_path"] = "/".join((GUEST_HOME, *EXTENSIONS_SUBDIR, uuid))
    return records


def _write_github_env(path: Path, records: list[dict]) -> None:
    tags = sorted({r["tag"] for r in records})
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"GNOME_E2E_BEHAVE_TAGS={behave_tags(records)}\n")
        handle.write(f"GNOME_E2E_REQUIRED_TAGS={' '.join(tags)}\n")
        handle.write(f"GNOME_E2E_STAGED_UUIDS={' '.join(r['uuid'] for r in records)}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan", help="print pinned source coordinates")
    p_plan.add_argument("profile")
    p_cmp = sub.add_parser("compare", help="compare two builds of one revision")
    p_cmp.add_argument("first", type=Path)
    p_cmp.add_argument("second", type=Path)
    p_val = sub.add_parser("validate", help="validate archives without extracting")
    p_val.add_argument("archives", nargs="+", type=Path)
    p_stage = sub.add_parser("stage", help="validate and stage into a guest home")
    p_stage.add_argument("--home", type=Path, required=True,
                         help="mounted guest home of the desktop user")
    p_stage.add_argument("--uid", type=int, default=1001)
    p_stage.add_argument("--gid", type=int, default=1001)
    p_stage.add_argument("--provenance", type=Path, required=True)
    p_stage.add_argument("--github-env", type=Path)
    p_stage.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            for key, value in plan(args.profile).items():
                print(f"{key}={value}")
            return 0
        if args.command == "compare":
            print(json.dumps(compare(args.first, args.second), indent=2))
            return 0
        if args.command == "validate":
            records = validate(args.archives)
            print(json.dumps(records, indent=2))
            return 0
        records = stage(args.home, args.archives, args.uid, args.gid)
    except (OSError, CandidateError, zipfile.BadZipFile) as exc:
        print(f"::error::extension candidate: {exc}", file=sys.stderr)
        return 1
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps({"candidates": records}, indent=2) + "\n",
                               encoding="utf-8")
    if args.github_env is not None:
        _write_github_env(args.github_env, records)
    for record in records:
        print(f"staged {record['uuid']} ({record['source_repo']}@{record['source_rev'][:8]}, "
              f"sha256 {record['zip_sha256']}) -> {record['staged_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
