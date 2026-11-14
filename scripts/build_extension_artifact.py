#!/usr/bin/env python3
"""Pack one hive extension from its pinned revision, offline, in GNOME OS devel.

The extension-validation lane (#909) tests the exact ZIP this produces, so the
ZIP must come from the revision the canonical contract pins
(``tests/shared/gnome_extensions_artifacts.py``) and the packaging recipe the
collection names (``tests/extensions/collection.json``), and the build must not
reach the network or any credential:

1. Fetch the pinned commit by SHA and check HEAD is that commit.
2. Run the recipe in the official GNOME OS devel image, pinned by digest, with
   ``--network=none`` and only the source tree mounted. Pass the digest the
   harness overlay was built from (``--builder-image``) so the extension is
   packed by the same GNOME OS build it is tested on.
3. Copy ``<uuid>.shell-extension.zip`` out, record its SHA256 and write
   ``build-provenance.json``. The staging step checks the same hash before
   extracting anything into the guest.

Usage: build_extension_artifact.py PROFILE OUTDIR [--builder-image REF@sha256:...]
Writes ``zip=`` and ``sha256=`` to ``$GITHUB_OUTPUT`` when it is set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.shared import gnome_extensions_artifacts as art  # noqa: E402

COLLECTION = Path(__file__).resolve().parents[1] / "tests" / "extensions" / "collection.json"
BUILDER = "quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-devel-nightly"


def build_plan(profile: str, collection_path: Path = COLLECTION) -> dict:
    """Source, revision and recipe for ``profile``; raises ValueError if unknown."""
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    if profile not in collection:
        raise ValueError(f"unknown extension profile: {profile!r}")
    entry = collection[profile]
    contract = art.find_contract(entry["uuid"])
    if contract is None or contract.source_repo != entry["repository"]:
        raise ValueError(f"profile {profile!r} has no matching canonical contract")
    if "package_command" in entry:
        recipe = shlex.split(entry["package_command"])
    else:
        recipe = ["gnome-extensions", "pack", ".", "--force"]
        recipe += [f"--extra-source={source}" for source in entry.get("package_sources", [])]
    return {
        "profile": profile,
        "uuid": contract.uuid,
        "source_repo": contract.source_repo,
        "source_rev": contract.source_rev,
        "package_recipe": contract.package_recipe,
        "recipe": recipe,
        "zip": f"{contract.uuid}.shell-extension.zip",
    }


def container_argv(image: str, source: Path, recipe: list[str]) -> list[str]:
    """The offline builder: no network, only the source tree mounted."""
    return [
        "podman", "run", "--rm", "--network=none", "--security-opt", "label=disable",
        "--volume", f"{source}:/src", "--workdir", "/src", image, *recipe,
    ]


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+ " + shlex.join(argv), flush=True)
    return subprocess.run(argv, check=True, text=True, **kwargs)


def fetch(repo: str, rev: str, dest: Path, run=_run) -> None:
    run(["git", "init", "--quiet", str(dest)])
    run(["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", f"https://github.com/{repo}", rev])
    run(["git", "-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    head = run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True).stdout.strip()
    if head != rev:
        raise RuntimeError(f"fetched {head}, expected pinned {rev}")


def resolve_builder(image: str = BUILDER, run=_run) -> str:
    """Pull the builder once and return it as an immutable digest reference."""
    if "@sha256:" in image:
        run(["podman", "pull", "--quiet", image], capture_output=True)
        return image
    run(["podman", "pull", "--quiet", image], capture_output=True)
    digest = run(["podman", "image", "inspect", "--format", "{{.Digest}}", image],
                 capture_output=True).stdout.strip()
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"builder image has no digest: {digest!r}")
    return f"{image.rsplit(':', 1)[0]}@{digest}"


def build(profile: str, out: Path, builder_image: str = BUILDER, run=_run) -> dict:
    plan = build_plan(profile)
    builder = resolve_builder(builder_image, run=run)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "src"
        fetch(plan["source_repo"], plan["source_rev"], source, run)
        run(container_argv(builder, source, plan["recipe"]))
        packed = source / plan["zip"]
        if not packed.is_file():
            raise RuntimeError(f"recipe produced no {plan['zip']}")
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(packed, out / plan["zip"])
    sha256 = hashlib.sha256((out / plan["zip"]).read_bytes()).hexdigest()
    provenance = {**plan, "builder_image": builder, "zip_sha256": sha256}
    (out / "build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("profile", help="key in tests/extensions/collection.json")
    parser.add_argument("out", type=Path, help="directory for the ZIP and its provenance")
    parser.add_argument("--builder-image", default=BUILDER,
                        help="GNOME OS devel image; a digest reference is used as given")
    args = parser.parse_args(argv)
    provenance = build(args.profile, args.out, args.builder_image)
    print(json.dumps(provenance, indent=2))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"zip={args.out / provenance['zip']}\nsha256={provenance['zip_sha256']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
