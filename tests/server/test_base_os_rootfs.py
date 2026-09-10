"""Tests for Bluefin Server Base OS DDI, root filesystem, and core invariants.

Covers:
- Root filesystem XFS DDI construction and deployment via systemd-repart
- Base OS stack toolchain (uutils-coreutils and bootstrap/bash.bst)
- Persistent /var partition (XFS) and automated mount via var.mount before local-fs.target
- Default console credentials and /etc/issue banner with KubeStellar dashboard URL
"""

from __future__ import annotations

import re
from pathlib import Path

from .conftest import load_systemd_conf, load_yaml


class TestBaseOsDdi:
    """Invariants for the XFS DDI OS payload image."""

    def test_ddi_element_formats_xfs_filesystem(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        assert ddi_bst.is_file(), f"Missing {ddi_bst}"
        content = ddi_bst.read_text(encoding="utf-8")

        # Must format using mkfs.xfs with proto directory /layer and label bluefin-root
        assert "mkfs.xfs -f -L bluefin-root -p /layer" in content

        # Pre-allocation with truncate and 4096-byte alignment for repart CopyBlocks=
        assert 'truncate -s "${TARGET_BYTES}"' in content
        assert "TARGET_BYTES=$(( (TARGET_BYTES + 4095) / 4096 * 4096 ))" in content

        # Zstd compression and SHA256SUMS manifest
        assert "zstd --rm -T0 -19 -q" in content
        assert 'sha256sum --binary "${FNAME}.zst" > SHA256SUMS' in content

        # xfsprogs dependency for mkfs.xfs
        data = load_yaml(ddi_bst)
        build_depends = [
            dep if isinstance(dep, str) else dep.get("filename", "")
            for dep in data.get("build-depends", [])
        ]
        assert "freedesktop-sdk.bst:components/xfsprogs.bst" in build_depends

    def test_repart_root_slot_a_configuration(self, files_dir: Path) -> None:
        root_conf = files_dir / "installer" / "repart.d" / "20-root-a.conf"
        assert root_conf.is_file(), f"Missing {root_conf}"
        parser = load_systemd_conf(root_conf)

        assert parser.has_section("Partition")
        part = parser["Partition"]
        assert part.get("Type") == "root"
        assert part.get("Label") == "bluefin-server-root-a"
        assert part.get("CopyBlocks") == "/dev/disk/by-partlabel/bluefin-installer-data"
        assert part.get("GrowFileSystem") == "yes"
        assert part.get("SizeMinBytes") == "4G"
        assert part.get("SizeMaxBytes") == "16G"

    def test_installer_stages_ddi_for_repart_copyblocks(self, elements_dir: Path) -> None:
        installer_bst = elements_dir / "oci" / "bluefin-server-installer.bst"
        assert installer_bst.is_file(), f"Missing {installer_bst}"
        data = load_yaml(installer_bst)

        build_deps = data.get("build-depends", [])
        ddi_dep = next(
            (
                dep for dep in build_deps
                if isinstance(dep, dict) and dep.get("filename") == "oci/bluefin-server-ddi.bst"
            ),
            None,
        )
        assert ddi_dep is not None, "Installer must stage oci/bluefin-server-ddi.bst"
        assert ddi_dep.get("config", {}).get("location") == "/ddi"

    def test_ddi_optimizes_and_indexes_modules(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")

        # Must run depmod and clean debug/static archives to keep image lean
        assert 'depmod -b /layer "${KVER}"' in content
        assert "find /layer -type f -name '*.debug' -delete" in content
        assert "find /layer -type f -name '*.a' -delete" in content
        assert 'rm -f "/layer/usr/lib/modules/${KVER}/vmlinux"' in content


class TestBaseOsToolchain:
    """Contracts for minimal userland: uutils-coreutils and bootstrap/bash."""

    def test_os_stack_includes_uutils_coreutils(self, elements_dir: Path) -> None:
        os_stack = elements_dir / "bluefin-server" / "os-stack.bst"
        assert os_stack.is_file(), f"Missing {os_stack}"
        data = load_yaml(os_stack)
        depends = data.get("depends", [])
        assert "bluefin-server/uutils-coreutils.bst" in depends

    def test_installer_stack_includes_uutils_coreutils(self, elements_dir: Path) -> None:
        installer_stack = elements_dir / "installer" / "installer-stack.bst"
        assert installer_stack.is_file(), f"Missing {installer_stack}"
        data = load_yaml(installer_stack)
        depends = data.get("depends", [])
        assert "bluefin-server/uutils-coreutils.bst" in depends

    def test_uutils_coreutils_creates_symlinks(self, elements_dir: Path) -> None:
        uutils_bst = elements_dir / "bluefin-server" / "uutils-coreutils.bst"
        assert uutils_bst.is_file(), f"Missing {uutils_bst}"
        content = uutils_bst.read_text(encoding="utf-8")
        assert "target/release/coreutils" in content
        assert 'ln -sr "%{install-root}/usr/bin/uutils-coreutils"' in content

    def test_os_stack_uses_bootstrap_bash_not_components(self, elements_dir: Path) -> None:
        os_stack = elements_dir / "bluefin-server" / "os-stack.bst"
        data = load_yaml(os_stack)
        depends = data.get("depends", [])
        assert "freedesktop-sdk.bst:bootstrap/bash.bst" in depends
        assert "freedesktop-sdk.bst:components/bash.bst" not in depends

    def test_installer_stack_uses_bootstrap_bash(self, elements_dir: Path) -> None:
        installer_stack = elements_dir / "installer" / "installer-stack.bst"
        data = load_yaml(installer_stack)
        depends = data.get("depends", [])
        assert "freedesktop-sdk.bst:bootstrap/bash.bst" in depends
        assert "freedesktop-sdk.bst:components/bash.bst" not in depends


class TestPersistentVarPartition:
    """Invariants for persistent /var partition and automated mount before local-fs.target."""

    def test_var_repart_configuration(self, files_dir: Path) -> None:
        var_conf = files_dir / "installer" / "repart.d" / "30-var.conf"
        assert var_conf.is_file(), f"Missing {var_conf}"
        parser = load_systemd_conf(var_conf)

        assert parser.has_section("Partition")
        part = parser["Partition"]
        assert part.get("Type") == "var"
        assert part.get("Label") == "var"
        assert part.get("Format") == "xfs"
        assert part.get("GrowFileSystem") == "yes"
        assert part.get("SizeMinBytes") == "4G"
        assert part.get("CopyFiles") == "/k0s.raw:/lib/k0s/k0s.raw"
        # Must NOT set FactoryReset=yes because systemd-sysinstall skips factory reset partitions
        assert part.get("FactoryReset") != "yes"

    def test_var_mount_unit_ordering_and_dependencies(self, files_dir: Path) -> None:
        mount_file = files_dir / "os" / "systemd" / "system" / "var.mount"
        assert mount_file.is_file(), f"Missing {mount_file}"
        parser = load_systemd_conf(mount_file)

        assert parser.has_section("Unit")
        unit = parser["Unit"]
        assert unit.get("DefaultDependencies") == "no"
        assert "local-fs.target" in unit.get("Before", "")
        assert "umount.target" in unit.get("Before", "")
        assert unit.get("Conflicts") == "umount.target"

        assert parser.has_section("Mount")
        mount = parser["Mount"]
        assert mount.get("What") == "/dev/disk/by-partlabel/var"
        assert mount.get("Where") == "/var"
        assert mount.get("Type") == "xfs"
        assert mount.get("Options") == "defaults"

        assert parser.has_section("Install")
        assert parser["Install"].get("WantedBy") == "local-fs.target"

    def test_var_mount_preset_enabled(self, files_dir: Path) -> None:
        preset_file = (
            files_dir / "os" / "systemd" / "system-preset" / "zz-enable-var-mount.preset"
        )
        assert preset_file.is_file(), f"Missing {preset_file}"
        assert preset_file.read_text(encoding="utf-8").strip() == "enable var.mount"

    def test_var_fstab_fallback_entry(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")
        assert "/dev/disk/by-partlabel/var /var xfs defaults 0 0" in content

    def test_var_mount_packaging_in_elements(self, elements_dir: Path) -> None:
        boot_element = elements_dir / "bluefin-server" / "os-k0s-first-boot.bst"
        assert boot_element.is_file()
        boot_data = load_yaml(boot_element)
        assert boot_data.get("config", {}).get("target") == "/usr/lib/systemd/system"

        preset_element = elements_dir / "bluefin-server" / "os-sshd-preset.bst"
        assert preset_element.is_file()
        preset_data = load_yaml(preset_element)
        assert preset_data.get("config", {}).get("target") == "/usr/lib/systemd/system-preset"


class TestDefaultConsoleCredentialsAndIssue:
    """Invariants for default console login credentials and the KubeStellar banner."""

    def test_issue_banner_contains_kubestellar_dashboard_url(self, files_dir: Path) -> None:
        issue_file = files_dir / "os" / "issue.d" / "40-kubestellar.issue"
        assert issue_file.is_file(), f"Missing {issue_file}"
        content = issue_file.read_text(encoding="utf-8")

        assert "Bluefin Server" in content
        assert "Default login: root / bluefin" in content
        assert "KubeStellar Console: http://\\4:8080/ (or http://127.0.0.1:8080 from host)" in content

    def test_issue_element_packaged_in_usr_lib_issue_d(self, elements_dir: Path) -> None:
        issue_bst = elements_dir / "bluefin-server" / "os-issue.bst"
        assert issue_bst.is_file(), f"Missing {issue_bst}"
        data = load_yaml(issue_bst)
        assert data.get("kind") == "import"
        assert data.get("config", {}).get("target") == "/usr/lib/issue.d"

        stack_bst = elements_dir / "bluefin-server" / "os-stack.bst"
        stack_data = load_yaml(stack_bst)
        assert "bluefin-server/os-issue.bst" in stack_data.get("depends", [])

    def test_default_shadow_root_password_hash(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")

        # Root password 'bluefin' with SHA-512 salt 'bluefin123'
        assert "root:$6$bluefin123$o2pQjPN1n3ZCnYUROlA01xAdnGO7mhVRAVw98x4xc8LAUIJv7b44bBNoER6fM4P.rrj4ePYFfkx9WvZICU8nt/" in content
        assert "chmod 0600 /layer/etc/shadow" in content

    def test_root_user_shell_and_credentials_declaration(
        self, files_dir: Path, elements_dir: Path
    ) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")
        assert "root:x:0:0:root:/root:/bin/bash" in content

        sysusers_file = files_dir / "os" / "sysusers.d" / "10-root-creds.conf"
        assert sysusers_file.is_file(), f"Missing {sysusers_file}"
        sysusers_content = sysusers_file.read_text(encoding="utf-8")
        assert re.search(r"^u\s+root\s+0\s+\"root\"\s+/root\s+/bin/bash", sysusers_content, re.MULTILINE)

    def test_securetty_consoles_allow_root_login(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")

        for console in ("tty0", "tty1", "ttyS0", "ttyS1", "console", "hvc0"):
            assert console in content

    def test_firstboot_masked_to_prevent_interactive_blocks(self, elements_dir: Path) -> None:
        ddi_bst = elements_dir / "oci" / "bluefin-server-ddi.bst"
        content = ddi_bst.read_text(encoding="utf-8")
        assert "ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service" in content
