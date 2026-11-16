"""Unit tests for scripts/build_extension_artifact.py (#909).

The commands are recorded, not run: no git fetch, podman or GNOME OS image.
"""
import hashlib
import json
from pathlib import Path

import pytest

from scripts import build_extension_artifact as builder
from tests.shared import gnome_extensions_artifacts as art


def test_just_perfection_plan_uses_its_build_script_at_the_pinned_rev():
    plan = builder.build_plan("just-perfection")
    contract = art.find_contract("just-perfection-desktop@just-perfection")
    assert plan["source_rev"] == contract.source_rev
    assert plan["source_repo"] == "gnome-extensions-hive/just-perfection"
    assert plan["recipe"] == ["bash", "scripts/build.sh"]
    assert plan["zip"] == "just-perfection-desktop@just-perfection.shell-extension.zip"


def test_root_packed_profile_adds_its_extra_sources():
    plan = builder.build_plan("stock-market")
    assert plan["recipe"] == ["gnome-extensions", "pack", ".", "--force",
                              "--extra-source=stocks_fetch.py", "--extra-source=language.js"]


def test_unknown_profile_is_refused():
    with pytest.raises(ValueError, match="unknown extension profile"):
        builder.build_plan("not-a-profile")


def test_builder_container_has_no_network_and_only_the_source_mounted():
    argv = builder.container_argv("img@sha256:" + "a" * 64, Path("/w/src"), ["bash", "scripts/build.sh"])
    assert "--network=none" in argv
    assert [a for a in argv if a.startswith("/w") or ":/src" in a] == ["/w/src:/src"]
    assert argv[-3:] == ["img@sha256:" + "a" * 64, "bash", "scripts/build.sh"]


class _Recorder:
    def __init__(self, head, digest="sha256:" + "b" * 64, pack=True):
        self.calls, self.head, self.digest, self.pack = [], head, digest, pack

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        out = ""
        if argv[-2:] == ["rev-parse", "HEAD"]:
            out = self.head + "\n"
        elif argv[:3] == ["podman", "image", "inspect"]:
            out = self.digest + "\n"
        elif argv[:2] == ["podman", "run"] and self.pack:
            source = Path(next(a for a in argv if a.endswith(":/src")).rsplit(":", 1)[0])
            (source / "just-perfection-desktop@just-perfection.shell-extension.zip").write_bytes(b"zip")
        return type("Done", (), {"stdout": out})()


def test_build_records_hash_and_builder_digest(tmp_path, monkeypatch):
    rev = builder.build_plan("just-perfection")["source_rev"]
    run = _Recorder(rev)
    monkeypatch.setattr(builder, "fetch", lambda repo, r, dest, run: dest.mkdir())
    image = "quay.io/x/y@sha256:" + "c" * 64
    provenance = builder.build("just-perfection", tmp_path / "out", image, run=run)
    assert provenance["builder_image"] == image
    assert provenance["zip_sha256"] == hashlib.sha256(b"zip").hexdigest()
    saved = json.loads((tmp_path / "out/build-provenance.json").read_text())
    assert saved == provenance
    packed = next(c for c in run.calls if c[:2] == ["podman", "run"])
    assert image in packed and "--network=none" in packed


def test_build_fails_when_the_recipe_produces_no_zip(tmp_path, monkeypatch):
    run = _Recorder("x", pack=False)
    monkeypatch.setattr(builder, "fetch", lambda repo, r, dest, run: dest.mkdir())
    with pytest.raises(RuntimeError, match="produced no"):
        builder.build("just-perfection", tmp_path / "out", "img@sha256:" + "d" * 64, run=run)


def test_fetch_refuses_a_head_other_than_the_pinned_rev(tmp_path):
    with pytest.raises(RuntimeError, match="expected pinned"):
        builder.fetch("o/r", "a" * 40, tmp_path / "src", run=_Recorder("b" * 40))


def test_tag_reference_is_resolved_to_its_digest():
    ref = builder.resolve_builder("quay.io/x/y:nightly", run=_Recorder("x"))
    assert ref == "quay.io/x/y@sha256:" + "b" * 64
