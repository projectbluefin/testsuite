"""Tests for SSH Security and preset configuration on Bluefin Server OS.

Covers:
- Presence of SSH tooling and host keys in the OS image for on-demand diagnostics
- Disabled by default via system-preset (disable sshd.service, disable sshd.socket)
- Bring-up diagnostic configuration drop-in contracts
"""

from __future__ import annotations

import re
from pathlib import Path

from .conftest import load_yaml


class TestSshPresentInOsImage:
    """Invariants ensuring SSH is built into the OS image for on-demand diagnostics."""

    def test_os_stack_includes_openssh_components(self, elements_dir: Path) -> None:
        os_stack = elements_dir / "bluefin-server" / "os-stack.bst"
        assert os_stack.is_file(), f"Missing {os_stack}"
        data = load_yaml(os_stack)
        depends = data.get("depends", [])

        # OpenSSH binaries and systemd units
        assert "freedesktop-sdk.bst:components/openssh-systemd.bst" in depends
        # Preset and configuration drop-ins
        assert "bluefin-server/os-sshd-preset.bst" in depends
        assert "bluefin-server/os-sshd-config.bst" in depends

    def test_ddi_element_pregenerates_host_keys(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        assert ddi_bst.is_file(), f"Missing {ddi_bst}"
        content = ddi_bst.read_text(encoding="utf-8")

        # Ed25519 and RSA host keys
        assert 'ssh-keygen -q -N "" -t ed25519 -f /layer/etc/ssh/ssh_host_ed25519_key' in content
        assert 'ssh-keygen -q -N "" -t rsa -b 3072 -f /layer/etc/ssh/ssh_host_rsa_key' in content

        # Key file permissions
        assert "chmod 0600 /layer/etc/ssh/ssh_host_*_key" in content
        assert "chmod 0644 /layer/etc/ssh/ssh_host_*.pub" in content

    def test_sshd_config_includes_dropin_directory(self, files_dir: Path) -> None:
        sshd_config = files_dir / "os" / "ssh" / "sshd_config"
        assert sshd_config.is_file(), f"Missing {sshd_config}"
        content = sshd_config.read_text(encoding="utf-8")
        assert re.search(r"^\s*Include\s+/etc/ssh/sshd_config\.d/\*\.conf", content, re.MULTILINE)

    def test_sshd_config_dropin_allows_bringup_login(self, files_dir: Path) -> None:
        dropin = files_dir / "os" / "ssh" / "sshd_config.d" / "bluefin-server.conf"
        assert dropin.is_file(), f"Missing {dropin}"
        content = dropin.read_text(encoding="utf-8")

        assert "PermitRootLogin yes" in content
        assert "PubkeyAuthentication yes" in content
        assert "PasswordAuthentication yes" in content
        assert "KbdInteractiveAuthentication yes" in content


class TestSshDisabledByDefaultViaPreset:
    """Invariants ensuring SSH daemon and socket are disabled by default."""

    def test_sshd_preset_file_disables_units(self, files_dir: Path) -> None:
        preset_file = (
            files_dir / "os" / "systemd" / "system-preset" / "zz-enable-sshd.preset"
        )
        assert preset_file.is_file(), f"Missing {preset_file}"
        lines = [line.strip() for line in preset_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]

        assert "disable sshd.service" in lines
        assert "disable sshd.socket" in lines
        assert not any(line.startswith("enable sshd") for line in lines)

    def test_no_presets_enable_sshd(self, files_dir: Path) -> None:
        presets_dir = files_dir / "os" / "systemd" / "system-preset"
        assert presets_dir.is_dir()

        for preset_path in presets_dir.glob("*.preset"):
            lines = preset_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                assert not re.search(r"^enable\s+sshd", stripped), (
                    f"Preset {preset_path.name} unexpectedly enables sshd: '{stripped}'"
                )

    def test_sshd_preset_packaged_to_usr_lib_systemd_system_preset(
        self, elements_dir: Path
    ) -> None:
        preset_element = elements_dir / "bluefin-server" / "os-sshd-preset.bst"
        assert preset_element.is_file(), f"Missing {preset_element}"
        data = load_yaml(preset_element)

        assert data.get("kind") == "import"
        assert data.get("config", {}).get("target") == "/usr/lib/systemd/system-preset"

        # The filename zz-enable-sshd.preset starts with 'zz-' to win lexical evaluation against default presets
        sources = data.get("sources", [])
        src = next((s for s in sources if isinstance(s, dict) and "files/os/systemd/system-preset" in s.get("path", "")), None)
        assert src is not None
