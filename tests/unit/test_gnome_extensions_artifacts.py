"""Unit tests for tests/shared/gnome_extensions_artifacts.py.

Covers every validation stage with synthetic ZIPs so the gate's contract logic
is proven without a GNOME OS guest or the ``gnome-extensions`` pack tool.
"""

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from tests.shared import gnome_extensions_artifacts as art


def _make_zip(path: Path, members: dict[str, str], uuid: str = "test@uuid") -> Path:
    """Write a ZIP whose metadata.json declares ``uuid`` (honoured even if the
    caller also passes a ``metadata.json``)."""
    members = {**members}
    members["metadata.json"] = json.dumps({"uuid": uuid})
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def _corrupt_zip(path: Path) -> Path:
    """A file that is neither a valid ZIP nor plain text."""
    path.write_bytes(bytes(range(256)) * 4)
    return path


# --- happy path ----------------------------------------------------------

def test_valid_archive_passes(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid",
        source_repo="x/y",
        source_rev="abc123",
        required_paths=("metadata.json", "extension.js"),
    )
    zip_path = _make_zip(tmp_path / "ok.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid
    assert result.uuid_found == "test@uuid"
    assert art.classify(result) == "ok"


# --- UUID mismatch -------------------------------------------------------

def test_uuid_mismatch_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "wrong.zip", {"metadata.json": "{}"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert not result.metadata_ok
    assert any("UUID mismatch" in e for e in result.errors)
    assert art.classify(result) == "metadata"


# --- missing required paths ----------------------------------------------

def test_missing_required_path_is_artifact_failure(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js", "missing.js"),
    )
    zip_path = _make_zip(tmp_path / "partial.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert "missing.js" in result.required_missing
    assert art.classify(result) == "artifact"


# --- SHA256 --------------------------------------------------------------

def test_sha256_matches_when_pinned(tmp_path):
    zip_path = _make_zip(tmp_path / "pinned.zip", {"extension.js": "x"}, uuid="test@uuid")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js"),
        zip_sha256=digest,
    )
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid, result.errors
    assert result.sha256_actual == digest
    assert art.classify(result) == "ok"


def test_sha256_pinned_in_uppercase_still_matches(tmp_path):
    zip_path = _make_zip(tmp_path / "upper.zip", {"extension.js": "x"}, uuid="test@uuid")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js"),
        zip_sha256=digest.upper(),
    )
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid, result.errors


def test_sha256_mismatch(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        zip_sha256="0" * 64,
    )
    zip_path = _make_zip(tmp_path / "h.zip", {"metadata.json": "{}"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert any("SHA256 mismatch" in e for e in result.errors)
    assert result.sha256_actual is not None


def test_sha256_is_skipped_when_unpinned(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "n.hash.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid
    assert result.sha256_actual is None


# --- unreadable archive --------------------------------------------------

def test_unreadable_archive_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _corrupt_zip(tmp_path / "not-a-zip.zip")
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def test_corrupt_archive_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _corrupt_zip(tmp_path / "corrupt.zip")

    # validate_extension_zip turns that harness failure into a classified result.
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def test_missing_file_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    result = art.validate_extension_zip(tmp_path / "absent.zip", contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def _rewrite_zip_member(zip_path: Path, name: str, content: bytes) -> Path:
    """Write a ZIP containing ``name`` with ``content`` (plus a dummy sibling so
    the archive is non-trivial)."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("extension.js", "x")
        zf.writestr(name, content)
    return zip_path


def test_malformed_metadata_json_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _rewrite_zip_member(tmp_path / "bad.json.zip", "metadata.json", b"{not json")
    with pytest.raises(art.ArtifactValidationError):
        art._parse_metadata(b"{not json")
    # The gate classifies it as an unsupported-metadata (metadata) failure.
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "metadata"


def test_non_object_metadata_json_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _rewrite_zip_member(tmp_path / "arr.zip", "metadata.json", b"[]")
    with pytest.raises(art.ArtifactValidationError):
        art._parse_metadata(b"[]")
    assert art.classify(art.validate_extension_zip(bad, contract)) == "metadata"


def test_non_utf8_metadata_json_is_metadata_failure(tmp_path):
    """json.loads raises UnicodeDecodeError (a ValueError, not a
    JSONDecodeError) on non-UTF-8 bytes; it must not escape the no-raise
    contract of validate_extension_zip."""
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _rewrite_zip_member(tmp_path / "utf16.zip", "metadata.json", b"\xff\xfe{")
    with pytest.raises(art.ArtifactValidationError):
        art._parse_metadata(b"\xff\xfe{")
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "metadata"


# --- hostile archives ----------------------------------------------------

def test_oversized_metadata_is_rejected_without_inflating(tmp_path):
    """A highly compressible metadata.json is refused on its declared size."""
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("extension.js", "x")
        zf.writestr("metadata.json", b"\0" * (art._MAX_METADATA_BYTES + 1))
    assert bomb.stat().st_size < art._MAX_METADATA_BYTES  # compresses tiny

    result = art.validate_extension_zip(bomb, contract)
    assert not result.valid
    assert any("implausibly large" in e for e in result.errors)
    assert art.classify(result) == "metadata"


def test_duplicate_member_names_are_rejected(tmp_path):
    """Two metadata.json members must never validate on one and install another."""
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json",),
    )
    dupe = tmp_path / "dupe.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(dupe, "w") as zf:
            zf.writestr("metadata.json", json.dumps({"uuid": "evil@uuid"}))
            zf.writestr("metadata.json", json.dumps({"uuid": "test@uuid"}))

    result = art.validate_extension_zip(dupe, contract)
    assert not result.valid
    assert any("duplicate member names" in e for e in result.errors)
    assert art.classify(result) == "artifact"


@pytest.mark.parametrize("name", [
    "../outside.js", "/absolute.js", "lib/../../outside.js",
    "./extension.js", "lib//API.js", "lib/./API.js",
    "C:/outside.js", r"lib\outside.js", "/", "bad\0suffix.js",
])
def test_unsafe_members_fail_before_metadata_read(tmp_path, monkeypatch, name):
    # zipfile's writer truncates at NUL; patch both headers to simulate an
    # externally produced archive while preserving the filename byte length.
    stored_name = name.replace("\0", "_")
    archive = _make_zip(tmp_path / "unsafe.zip", {stored_name: "x"})
    if "\0" in name:
        archive.write_bytes(archive.read_bytes().replace(stored_name.encode(), name.encode()))
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")

    def unexpected_read(*args):
        pytest.fail("unsafe archives must be rejected before inflating metadata")

    monkeypatch.setattr(art, "_metadata_in", unexpected_read)
    result = art.validate_extension_zip(archive, contract)
    assert art.classify(result) == art.CATEGORY_ARTIFACT
    assert "unsafe archive path" in result.errors[0]
    with pytest.raises(art.ArtifactValidationError) as failure:
        art.read_archive_uuid(archive)
    assert failure.value.category == art.CATEGORY_ARTIFACT


@pytest.mark.parametrize("mode", [
    stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFDIR,
])
def test_links_and_special_members_are_artifact_failures(tmp_path, mode):
    archive = _make_zip(tmp_path / "special.zip", {})
    member = zipfile.ZipInfo("extension.js")
    member.create_system = 3
    member.external_attr = (mode | 0o755) << 16
    with zipfile.ZipFile(archive, "a") as zf:
        zf.writestr(member, "../../outside")
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    result = art.validate_extension_zip(archive, contract)
    assert art.classify(result) == art.CATEGORY_ARTIFACT
    assert "unsupported archive member type" in result.errors[0]


@pytest.mark.parametrize("members", [
    {"lib": "file", "lib/API.js": "x"},
    {"lib": "file", "lib/": ""},
    {"lib/API.js": "x", "lib": "file"},
])
def test_file_directory_aliases_are_rejected(tmp_path, members):
    archive = _make_zip(tmp_path / "alias.zip", members)
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    result = art.validate_extension_zip(archive, contract)
    assert art.classify(result) == art.CATEGORY_ARTIFACT
    assert "file/directory conflicts" in result.errors[0]


def test_regular_directory_entries_remain_supported(tmp_path):
    archive = _make_zip(tmp_path / "normal.zip", {"lib/": "", "lib/API.js": "x"})
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "lib/API.js"),
    )
    assert art.validate_extension_zip(archive, contract).valid


def test_cli_rejects_hostile_member_with_explicit_pair(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS[:1])
    archive = _make_zip(tmp_path / "hostile.zip", {"a.js": "x", "../escape": "x"}, uuid="a@x")
    assert art.main([f"a@x={archive}"]) == 1
    assert "[FAIL/artifact]" in capsys.readouterr().out


def test_hash_mismatch_precedes_member_inspection(tmp_path, monkeypatch):
    archive = _make_zip(tmp_path / "hash.zip", {"../escape": "x"})
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc", zip_sha256="0" * 64,
    )

    def unexpected_inspection(*args):
        pytest.fail("hash mismatch must block archive inspection")

    monkeypatch.setattr(art, "_check_members", unexpected_inspection)
    result = art.validate_extension_zip(archive, contract)
    assert art.classify(result) == art.CATEGORY_ARTIFACT
    assert "SHA256 mismatch" in result.errors[0]


def test_cli_uuid_resolution_rejects_hostile_zip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS[:1])
    archive = _make_zip(tmp_path / "hostile.zip", {"a.js": "x", "../escape": "x"}, uuid="a@x")
    assert art.main([str(archive)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL/artifact]" in out
    assert "unsafe archive path" in out


# --- canonical contracts -------------------------------------------------

def test_canonical_contracts_have_uuids_and_revs():
    assert len(art.CANONICAL_CONTRACTS) == 4
    for contract in art.CANONICAL_CONTRACTS:
        assert "@" in contract.uuid
        assert len(contract.source_rev) == 40
        assert contract.required_paths
        assert "metadata.json" in contract.required_paths


def test_find_contract_roundtrip():
    contract = art.find_contract("stock-market@binhnguyensoft.com")
    assert contract is not None
    assert "stocks_fetch.py" in contract.required_paths
    assert art.find_contract("does-not-exist@uuid") is None


def test_canonical_contracts_require_what_packaging_ships():
    """Contracts must cover the members the shell actually loads, not just the
    manifest — otherwise an unloadable ZIP validates and the guest failure is
    misattributed."""
    jp = art.find_contract("just-perfection-desktop@just-perfection")
    assert jp is not None
    # scripts/build.sh packs the compiled resource bundle and lib/ as extras.
    assert "data/resources.gresource" in jp.required_paths
    assert any(p.startswith("lib/") for p in jp.required_paths)
    assert any(p.startswith("schemas/") for p in jp.required_paths)

    # Both binhnguyensoft extensions that commit a compiled schema must require
    # it: gschemas.compiled is what the shell reads for their settings.
    for uuid in ("sjc-gold@binhnguyensoft.com", "stock-market@binhnguyensoft.com"):
        contract = art.find_contract(uuid)
        assert contract is not None
        assert "schemas/gschemas.compiled" in contract.required_paths


def test_canonical_contracts_pin_no_hash_yet():
    """Stage 0 is documented as inert today; assert that stays explicit so the
    TODO(#908) is retired deliberately rather than silently."""
    assert all(c.zip_sha256 is None for c in art.CANONICAL_CONTRACTS)


# --- explicit failure categories ----------------------------------------

def test_category_is_recorded_on_the_result(tmp_path):
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "cat.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.category == art.CATEGORY_METADATA
    assert art.classify(result) == "metadata"


def test_classify_does_not_depend_on_message_wording(tmp_path):
    """Rewording an error must not reclassify the failure."""
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "reword.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    result.errors[0] = "the archive names a different extension"
    assert art.classify(result) == "metadata"


def test_first_category_wins_when_several_checks_fail(tmp_path):
    contract = art.ExtensionContract(
        uuid="real@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "missing.js"),
    )
    zip_path = _make_zip(tmp_path / "both.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert len(result.errors) == 2
    assert art.classify(result) == "metadata"


def test_validate_all_reports_unknown_uuid(tmp_path):
    zip_path = _make_zip(tmp_path / "x.zip", {"metadata.json": "{}"}, uuid="test@uuid")
    results = art.validate_all({"unknown@uuid": zip_path})
    assert len(results) == 1
    assert not results[0].valid
    assert results[0].errors[0].startswith("no canonical contract")


# --- CLI ------------------------------------------------------------------

_CLI_CONTRACTS = tuple(
    art.ExtensionContract(
        uuid=f"{letter}@x",
        source_repo="r",
        source_rev="r" * 40,
        required_paths=("metadata.json", f"{letter}.js"),
        package_recipe=art.RECIPE_PACK_FROM_ROOT,
    )
    for letter in ("a", "b", "c", "d")
)


def _stage_all(tmp_path: Path) -> dict[str, Path]:
    """One valid ZIP per :data:`_CLI_CONTRACTS`, named so that alphabetical glob
    order differs from canonical order."""
    names = {"a@x": "zeta.zip", "b@x": "alpha.zip", "c@x": "yankee.zip", "d@x": "beta.zip"}
    return {
        contract.uuid: _make_zip(
            tmp_path / names[contract.uuid],
            {f"{contract.uuid[0]}.js": "x"},
            uuid=contract.uuid,
        )
        for contract in _CLI_CONTRACTS
    }


def test_main_pairs_by_declared_uuid_not_argv_order(tmp_path, monkeypatch, capsys):
    """The documented ``*.zip`` glob must pass whatever order the shell expands.

    Glob order is alphabetical by filename, which does not match canonical
    contract order; pairing positionally made two good artifacts fail with a
    bogus 'UUID mismatch' — exactly the misattribution #909 exists to prevent.
    """
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS)
    zips = _stage_all(tmp_path)

    # Alphabetical (glob) order != canonical order.
    shuffled = [str(zips[u]) for u in ("b@x", "d@x", "a@x", "c@x")]
    assert art.main(shuffled) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert "4/4 passed" in out


def test_main_accepts_explicit_uuid_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS)
    zips = _stage_all(tmp_path)
    args = [f"{uuid}={zips[uuid]}" for uuid in ("d@x", "c@x", "b@x", "a@x")]
    assert art.main(args) == 0


def test_main_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS)
    zips = _stage_all(tmp_path)
    ordered = [str(zips[u]) for u in ("a@x", "b@x", "c@x", "d@x")]

    # All pass -> exit 0.
    assert art.main(ordered) == 0
    # A structurally broken artifact -> exit 1.
    incomplete = _make_zip(tmp_path / "cbad.zip", {}, uuid="c@x")  # missing c.js
    assert art.main([*ordered[:2], str(incomplete), ordered[3]]) == 1
    # A missing extension is a harness failure, not a silent pass.
    assert art.main(ordered[:1]) == 1
    # No arguments at all -> exit 2 (usage).
    assert art.main([]) == 2


def test_main_reports_missing_and_unknown_artifacts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS)
    zips = _stage_all(tmp_path)
    stranger = _make_zip(tmp_path / "stranger.zip", {"a.js": "x"}, uuid="nobody@x")

    assert art.main([str(zips["a@x"]), str(stranger)]) == 1
    out = capsys.readouterr().out
    assert "no canonical contract" in out
    assert "no staged archive declares this UUID" in out
    assert "[FAIL/harness]" in out
    assert "[FAIL/metadata]" in out


def test_main_rejects_the_same_uuid_staged_twice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS)
    zips = _stage_all(tmp_path)
    dupe = _make_zip(tmp_path / "a-again.zip", {"a.js": "x"}, uuid="a@x")

    assert art.main([str(p) for p in zips.values()] + [str(dupe)]) == 1
    assert "staged twice" in capsys.readouterr().out


def test_main_reports_contract_identity(tmp_path, monkeypatch, capsys):
    """#909 step 1 wants revision, UUID, recipe and hash visible in the report."""
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS[:1])
    zips = _stage_all(tmp_path)
    assert art.main([str(zips["a@x"])]) == 0
    out = capsys.readouterr().out
    assert "recipe=" + art.RECIPE_PACK_FROM_ROOT in out
    assert "sha256=unpinned" in out
    assert "a@x" in out


def test_main_reports_classify_category(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", _CLI_CONTRACTS[:1])

    # Right UUID, wrong contents -> the extension's own artifact failure.
    incomplete = _make_zip(tmp_path / "w.zip", {}, uuid="a@x")
    assert art.main([str(incomplete)]) == 1
    assert "[FAIL/artifact]" in capsys.readouterr().out

    broken = _corrupt_zip(tmp_path / "broken.zip")
    assert art.main([str(broken)]) == 1
    assert "[FAIL/harness]" in capsys.readouterr().out


# --- UUID resolution -----------------------------------------------------

def test_read_archive_uuid_roundtrip(tmp_path):
    zip_path = _make_zip(tmp_path / "u.zip", {"a.js": "x"}, uuid="a@x")
    assert art.read_archive_uuid(zip_path) == "a@x"


def test_read_archive_uuid_categorises_failures(tmp_path):
    broken = _corrupt_zip(tmp_path / "b.zip")
    with pytest.raises(art.ArtifactValidationError) as unreadable:
        art.read_archive_uuid(broken)
    assert unreadable.value.category == art.CATEGORY_HARNESS

    no_uuid = _rewrite_zip_member(tmp_path / "n.zip", "metadata.json", b"{}")
    with pytest.raises(art.ArtifactValidationError) as bad_meta:
        art.read_archive_uuid(no_uuid)
    assert bad_meta.value.category == art.CATEGORY_METADATA


def test_pair_archives_keeps_paths_containing_equals(tmp_path):
    odd = tmp_path / "a=b.zip"
    _make_zip(odd, {"a.js": "x"}, uuid="a@x")
    pairs, problems = art.pair_archives([str(odd)])
    assert problems == []
    assert pairs == {"a@x": odd}


# --- package recipe identity --------------------------------------------

def test_canonical_contracts_declare_a_package_recipe():
    """#909 step 1 pins the package recipe, so it must be assertable data."""
    for contract in art.CANONICAL_CONTRACTS:
        assert contract.package_recipe != art.RECIPE_UNSPECIFIED
        assert contract.package_recipe in (
            art.RECIPE_BUILD_SH, art.RECIPE_PACK_FROM_ROOT
        )
    jp = art.find_contract("just-perfection-desktop@just-perfection")
    assert jp is not None and jp.package_recipe == art.RECIPE_BUILD_SH
    sjc = art.find_contract("sjc-gold@binhnguyensoft.com")
    assert sjc is not None and sjc.package_recipe == art.RECIPE_PACK_FROM_ROOT


def test_contract_identity_names_every_pinned_field():
    contract = art.ExtensionContract(
        uuid="a@x", source_repo="r/s", source_rev="f" * 40,
        package_recipe=art.RECIPE_BUILD_SH, zip_sha256="AB" * 32,
    )
    identity = contract.identity
    assert "a@x" in identity
    assert "r/s@ffffffff" in identity
    assert art.RECIPE_BUILD_SH in identity
    assert ("ab" * 32) in identity
