"""Tests for systemd-sysupdate, updatectl contracts, and GPG signature verification.

Covers:
- Transfer definitions (50-root.transfer, 60-uki.transfer, 70-k0s.transfer)
- Mandatory @v wildcard in MatchPattern= across both [Source] and [Target]
- Valid Target types (regular-file, partition)
- GPG signature verification against import-pubring.gpg
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .conftest import load_systemd_conf, load_yaml

VALID_TARGET_TYPES = {"regular-file", "partition"}
RELEASE_BASE_URL = "https://github.com/projectbluefin/server/releases/latest/download/"


def get_all_transfer_paths(files_dir: Path) -> list[Path]:
    """Find all sysupdate transfer files in standard and component directories."""
    paths: list[Path] = []
    os_sysupdate = files_dir / "os" / "sysupdate.d"
    k0s_sysupdate = files_dir / "os" / "sysupdate.k0s.d"
    if os_sysupdate.is_dir():
        paths.extend(sorted(os_sysupdate.glob("*.transfer")))
    if k0s_sysupdate.is_dir():
        paths.extend(sorted(k0s_sysupdate.glob("*.transfer")))
    return paths


class TestSysupdateTransfers:
    """Validation of sysupdate transfer files and schema."""

    def test_expected_transfers_exist(self, files_dir: Path) -> None:
        transfers = {p.name for p in get_all_transfer_paths(files_dir)}
        expected = {"50-root.transfer", "60-uki.transfer", "70-k0s.transfer"}
        assert expected.issubset(transfers), f"Missing transfers: {expected - transfers}"

    def test_transfer_filenames_are_numbered_and_unique(self, files_dir: Path) -> None:
        transfer_paths = get_all_transfer_paths(files_dir)
        assert len(transfer_paths) >= 3

        prefixes: list[str] = []
        for path in transfer_paths:
            assert re.fullmatch(r"[0-9]{2}-[a-z0-9-]+\.transfer", path.name), (
                f"Transfer filename '{path.name}' must follow NN-name.transfer naming convention"
            )
            prefix = path.name.split("-", 1)[0]
            prefixes.append(prefix)

        assert len(prefixes) == len(set(prefixes)), f"Duplicate transfer ordering prefixes: {prefixes}"

    def test_transfer_has_required_sections(self, files_dir: Path) -> None:
        for path in get_all_transfer_paths(files_dir):
            parser = load_systemd_conf(path)
            for section in ("Transfer", "Source", "Target"):
                assert parser.has_section(section), (
                    f"Transfer file '{path.name}' is missing mandatory section [{section}]"
                )

    def test_mandatory_at_v_wildcard_in_source_and_target(self, files_dir: Path) -> None:
        for path in get_all_transfer_paths(files_dir):
            parser = load_systemd_conf(path)
            src_pattern = parser["Source"].get("MatchPattern", "")
            tgt_pattern = parser["Target"].get("MatchPattern", "")

            assert "@v" in src_pattern, (
                f"Transfer '{path.name}' [Source] MatchPattern='{src_pattern}' missing mandatory '@v' token"
            )
            assert "@v" in tgt_pattern, (
                f"Transfer '{path.name}' [Target] MatchPattern='{tgt_pattern}' missing mandatory '@v' token"
            )

            # Ensure @v is bounded with non-empty prefix and suffix
            src_prefix, _, src_suffix = src_pattern.partition("@v")
            assert src_prefix != "", f"Transfer '{path.name}' [Source] MatchPattern has empty prefix before @v"
            assert src_suffix != "", f"Transfer '{path.name}' [Source] MatchPattern has empty suffix after @v"

    def test_valid_target_types(self, files_dir: Path) -> None:
        for path in get_all_transfer_paths(files_dir):
            parser = load_systemd_conf(path)
            tgt_type = parser["Target"].get("Type", "")
            assert tgt_type in VALID_TARGET_TYPES, (
                f"Transfer '{path.name}' has invalid Target Type='{tgt_type}'. Must be one of {VALID_TARGET_TYPES}"
            )

    def test_50_root_transfer_contract(self, files_dir: Path) -> None:
        path = files_dir / "os" / "sysupdate.d" / "50-root.transfer"
        assert path.is_file(), f"Missing {path}"
        parser = load_systemd_conf(path)

        assert parser["Source"].get("Type") == "url-file"
        assert parser["Source"].get("Path") == RELEASE_BASE_URL
        assert parser["Source"].get("MatchPattern") == "bluefin-server-ddi-@v.raw.zst"

        assert parser["Target"].get("Type") == "partition"
        assert parser["Target"].get("Path") == "auto"
        # Must match both slot A and slot B for A/B rollback
        tgt_pattern = parser["Target"].get("MatchPattern", "")
        assert "bluefin-server-root-@v_a" in tgt_pattern
        assert "bluefin-server-root-@v_b" in tgt_pattern

    def test_60_uki_transfer_contract(self, files_dir: Path) -> None:
        path = files_dir / "os" / "sysupdate.d" / "60-uki.transfer"
        assert path.is_file(), f"Missing {path}"
        parser = load_systemd_conf(path)

        assert parser["Source"].get("Type") == "url-file"
        assert parser["Source"].get("Path") == RELEASE_BASE_URL
        assert parser["Source"].get("MatchPattern") == "bluefin-server-@v.efi"

        assert parser["Target"].get("Type") == "regular-file"
        assert parser["Target"].get("Path") == "/efi/EFI/Linux"
        assert parser["Target"].get("MatchPattern") == "bluefin-server-@v.efi"

    def test_70_k0s_transfer_contract(self, files_dir: Path) -> None:
        path = files_dir / "os" / "sysupdate.k0s.d" / "70-k0s.transfer"
        assert path.is_file(), f"Missing {path}"
        parser = load_systemd_conf(path)

        assert parser["Source"].get("Type") == "url-file"
        assert parser["Source"].get("Path") == RELEASE_BASE_URL
        assert parser["Source"].get("MatchPattern") == "k0s-@v.raw.zst"

        assert parser["Target"].get("Type") == "regular-file"
        assert parser["Target"].get("Path") == "/var/lib/k0s"
        assert parser["Target"].get("MatchPattern") == "k0s-@v.raw"
        assert parser["Target"].get("CurrentSymlink") == "k0s.raw"
        assert parser["Target"].get("Mode") == "0644"

    def test_source_artifacts_correspond_to_elements(
        self, files_dir: Path, all_elements_text: str
    ) -> None:
        for path in get_all_transfer_paths(files_dir):
            parser = load_systemd_conf(path)
            src_pattern = parser["Source"].get("MatchPattern", "")
            prefix, _, suffix = src_pattern.partition("@v")
            clean_suffix = suffix.removesuffix(".zst")

            pattern = re.compile(re.escape(prefix) + r"%\{[a-z0-9-]+\}" + re.escape(clean_suffix))
            assert pattern.search(all_elements_text), (
                f"Transfer '{path.name}' pattern '{src_pattern}' not matched by any BuildStream element output"
            )


class TestGpgVerificationAndTrust:
    """Invariants for GPG signature verification against import-pubring.gpg."""

    def test_import_pubring_keyring_file_exists_and_is_valid_openpgp(
        self, files_dir: Path
    ) -> None:
        keyring = files_dir / "os" / "sysupdate-keys" / "import-pubring.gpg"
        assert keyring.is_file(), f"Missing {keyring}"
        content = keyring.read_bytes()
        assert len(content) > 100, f"Keyring file {keyring} is unexpectedly small ({len(content)} bytes)"

        # Check OpenPGP packet tag (byte 0)
        # RFC 4880: Tag 6 (Public Key Packet) in old format is 0x98 or 0x99
        first_byte = content[0]
        assert first_byte in (0x98, 0x99), f"Unexpected OpenPGP header byte: 0x{first_byte:02x}"

        # If gpg tool is installed, inspect packets to verify identity
        if shutil.which("gpg"):
            res = subprocess.run(
                ["gpg", "--list-packets", str(keyring)],
                capture_output=True,
                text=True,
                check=True,
            )
            assert "Bluefin Server Release Signing" in res.stdout
            assert "709B547795F99C34" in res.stdout

    def test_keyring_packaged_into_usr_lib_systemd(self, elements_dir: Path) -> None:
        keys_element = elements_dir / "bluefin-server" / "os-sysupdate-keys.bst"
        assert keys_element.is_file(), f"Missing {keys_element}"
        data = load_yaml(keys_element)
        assert data.get("kind") == "import"
        # Standard systemd-sysupdate location is /usr/lib/systemd/import-pubring.gpg
        assert data.get("config", {}).get("target") == "/usr/lib/systemd"

    def test_os_stack_includes_keys_and_gnupg(self, elements_dir: Path) -> None:
        os_stack = elements_dir / "bluefin-server" / "os-stack.bst"
        assert os_stack.is_file(), f"Missing {os_stack}"
        data = load_yaml(os_stack)
        depends = data.get("depends", [])

        assert "bluefin-server/os-sysupdate-keys.bst" in depends, (
            "os-stack must depend on os-sysupdate-keys.bst"
        )
        assert "freedesktop-sdk.bst:components/gnupg.bst" in depends, (
            "os-stack must include gnupg so systemd-sysupdate can execute gpg for verification"
        )


class TestSysupdateIntegration:
    """Integration of sysupdate with kured hook and timer components."""

    def test_kured_hook_conf_reboot_coordination(self, files_dir: Path, elements_dir: Path) -> None:
        hook_file = (
            files_dir / "os" / "systemd" / "systemd-sysupdate.service.d" / "kured-hook.conf"
        )
        assert hook_file.is_file(), f"Missing {hook_file}"
        parser = load_systemd_conf(hook_file)
        assert parser.has_section("Service")
        exec_post = parser["Service"].get("ExecStartPost", "")
        assert "/var/run/reboot-required" in exec_post or "touch" in exec_post

        hook_element = elements_dir / "bluefin-server" / "os-kured-hook.bst"
        assert hook_element.is_file()
        hook_data = load_yaml(hook_element)
        assert hook_data.get("config", {}).get("target") == "/usr/lib/systemd/system/systemd-sysupdate.service.d"

    def test_os_stack_includes_sysupdate_components(self, elements_dir: Path) -> None:
        os_stack = elements_dir / "bluefin-server" / "os-stack.bst"
        data = load_yaml(os_stack)
        depends = data.get("depends", [])

        assert "bluefin-server/os-sysupdate.bst" in depends
        assert "bluefin-server/os-k0s-sysupdate.bst" in depends
        assert "bluefin-server/os-kured-hook.bst" in depends
