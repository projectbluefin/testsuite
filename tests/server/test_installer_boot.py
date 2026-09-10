"""Tests for Bluefin Server installer workflows and UEFI fallback bootloader staging.

Covers:
- systemd-sysinstall interactive and unattended workflows
- Target disk ESP staging of /EFI/BOOT/BOOTX64.EFI for universal UEFI boot compatibility
- UKI assembly and dracut driver contracts
"""

from __future__ import annotations

import re
from pathlib import Path

from .conftest import load_systemd_conf


class TestSysinstallWorkflows:
    """Invariants for systemd-sysinstall execution modes (interactive vs unattended)."""

    def test_installer_wrapper_and_override_presence(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        assert installer_bst.is_file(), f"Missing {installer_bst}"
        content = installer_bst.read_text(encoding="utf-8")

        # Generates bluefin-sysinstall wrapper script
        assert "cat > /layer/usr/bin/bluefin-sysinstall << 'EOF'" in content
        assert "chmod +x /layer/usr/bin/bluefin-sysinstall" in content

        # Systemd service drop-in override
        assert "systemd-sysinstall.service.d/override.conf" in content
        assert "ExecStart=/usr/bin/bluefin-sysinstall" in content
        assert "After=systemd-udev-settle.service" in content
        assert "Wants=systemd-udev-settle.service" in content
        assert "SuccessAction=poweroff" in content
        assert "FailureAction=poweroff" in content

    def test_cmdline_reading_without_cat_overhead(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")
        assert 'CMDLINE="$(< /proc/cmdline)"' in content
        assert 'CMDLINE="$(cat /proc/cmdline' not in content

    def test_unattended_workflow_contract(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # Unattended detection
        assert 'if [[ " ${CMDLINE} " == *" unattended "* ]]; then' in content

        # Required unattended flags passed to systemd-sysinstall
        assert "--kernel=/usr/lib/bluefin-server/bluefin-server.efi" in content
        assert "--erase=yes" in content
        assert "--confirm=no" in content
        assert "--summary=no" in content
        assert "--variables=yes" in content
        assert "--reboot=no" in content
        assert "--mute-console=yes" in content
        assert '"${TARGET_DISK}" < /dev/null' in content

        # Fails if no target disk found
        assert "ERROR: No suitable target disk found for unattended installation!" in content

    def test_interactive_workflow_contract(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # Interactive branch flags
        assert "--copy-locale=yes" in content
        assert "--copy-keymap=yes" in content
        assert "--copy-timezone=yes" in content
        assert "systemctl reboot" in content

    def test_target_disk_auto_detection_excludes_installer(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # Resolves installer data partition to prevent overwriting the installation medium
        assert 'readlink -f /dev/disk/by-partlabel/bluefin-installer-data' in content
        assert '[[ "${INSTALLER_PART}" == "${name}"* ]]' in content


class TestUefiFallbackBootloader:
    """Invariants for UEFI removable media fallback /EFI/BOOT/BOOTX64.EFI staging."""

    def test_stage_fallback_bootloader_function_definition(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        assert "stage_fallback_bootloader() {" in content
        # Discovers ESP vfat partition on target
        assert 'if [ "${fstype}" = "vfat" ]; then' in content
        # Mounts ESP
        assert 'mount -t vfat "${esp_dev}" /mnt/esp' in content
        assert "mkdir -p /mnt/esp/EFI/BOOT" in content

        # Ordered candidate priority
        candidates_str = (
            "/mnt/esp/EFI/systemd/systemd-bootx64.efi \\\n"
            "                /mnt/esp/flatcar/bluefin-server.efi \\\n"
            "                /mnt/esp/EFI/Linux/bluefin-server.efi \\\n"
            "                /usr/lib/bluefin-server/bluefin-server.efi"
        )
        assert candidates_str in content

        # Staged directly to BOOTX64.EFI
        assert 'cp -a "${candidate}" /mnt/esp/EFI/BOOT/BOOTX64.EFI' in content
        assert "umount /mnt/esp || true" in content

    def test_fallback_staging_executed_in_both_workflows(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # stage_fallback_bootloader must be invoked in both unattended and interactive paths
        unattended_block = content.partition('echo "==> Running in UNATTENDED mode..."')[2].partition("else")[0]
        interactive_block = content.partition('echo "==> Running in INTERACTIVE mode..."')[2].partition("fi\n      EOF")[0]

        assert "stage_fallback_bootloader" in unattended_block
        assert "stage_fallback_bootloader" in interactive_block

    def test_esp_repart_configuration(self, files_dir: Path) -> None:
        esp_conf = files_dir / "installer" / "repart.d" / "10-esp.conf"
        assert esp_conf.is_file(), f"Missing {esp_conf}"
        parser = load_systemd_conf(esp_conf)

        assert parser.has_section("Partition")
        part = parser["Partition"]
        assert part.get("Type") == "esp"
        assert part.get("Format") == "vfat"
        assert part.get("SizeMinBytes") == "500M"
        assert part.get("SizeMaxBytes") == "1G"

    def test_installer_media_stages_bootx64_efi(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # Installer medium itself must place UKI at /EFI/BOOT/BOOTX64.EFI
        assert "--output=/layer/boot/efi/EFI/BOOT/BOOTX64.EFI" in content

    def test_target_os_uki_configuration(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")

        # Target UKI command
        assert "--output=/target-root/boot/EFI/Linux/bluefin-server.efi" in content
        assert "cp /target-root/boot/EFI/Linux/bluefin-server.efi /layer/usr/lib/bluefin-server/bluefin-server.efi" in content

        # Target kernel command line
        cmdline_match = re.search(
            r'ukify build\s+.*?--cmdline="([^"]+)".*?--output=/target-root/boot/EFI/Linux/bluefin-server\.efi',
            content,
            re.DOTALL,
        )
        assert cmdline_match is not None
        assert cmdline_match.group(1) == "rw console=ttyS0,115200 console=tty0 quiet loglevel=3 audit=0"

        # Dracut includes required storage and filesystem drivers
        assert '--add-drivers "virtio virtio_blk virtio_pci virtio_scsi nvme nvme_core xfs erofs overlay"' in content

    def test_installer_preloads_nvme_and_settles_udev(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        content = installer_bst.read_text(encoding="utf-8")
        assert "modprobe -q nvme || true" in content
        assert "modprobe -q nvme_core || true" in content
        assert "udevadm settle --timeout=15 || true" in content
