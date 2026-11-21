"""Regression checks for shared E2E workflow setup."""

from pathlib import Path


def _workflow(name: str) -> str:
    return (
        Path(__file__).parents[2] / ".github" / "workflows" / name
    ).read_text()


def test_e2e_preserves_image_enabled_extensions():
    workflow = _workflow("e2e.yml")
    local_override = workflow.partition(
        'sudo mkdir -p "${DEP}/etc/dconf/db/local.d"'
    )[2].partition("sudo chroot")[0]

    assert "allow-extension-installation=true" in local_override
    assert "enabled-extensions" not in local_override
    assert "gnome-extensions enable unsafe-mode@bluefin-test" in workflow


def test_e2e_keeps_tailscale_running_with_sufficient_storage():
    workflow = _workflow("e2e.yml")

    assert "fallocate -l 40G disk.raw" in workflow
    assert "systemd.mask=tailscaled.service" not in workflow
    assert "idle-delay 0" in workflow
    assert "lock-enabled false" in workflow
    assert "pkill -x gnome-initial-setup" not in workflow


def test_manual_runs_checkout_the_selected_fork_ref_without_changing_callers():
    reusable = _workflow("e2e.yml")
    manual = _workflow("manual.yml")

    assert 'default: "projectbluefin/testsuite"' in reusable
    assert "repository: ${{ inputs.test_repository }}" in reusable
    assert "test_repository: ${{ github.repository }}" in manual


def test_e2e_composefs_firmware_boot_branch_for_dakota():
    """Dakota is composefs-native with no bootupd, so its lifecycle reboots
    must go through the OVMF firmware path, not direct kernel boot (#1215,
    #1023). The install uses --composefs-backend and a detected composefs
    backend forces FIRMWARE_BOOT=true."""
    workflow = _workflow("e2e.yml")

    # Composefs is detected from the image's install config, and a detected
    # composefs backend forces the firmware-boot path (no bootupd to use). The
    # composefs branch is a fallback after the bootupctl probe, and it sets
    # FIRMWARE_BOOT=true.
    assert "grep -lq composefs-backend /usr/lib/bootc/install/*.toml" in workflow
    composefs_probe = workflow.index("grep -lq composefs-backend /usr/lib/bootc/install/*.toml")
    assert workflow.index("FIRMWARE_BOOT=true", composefs_probe) > composefs_probe
    # dakota's install config names no backend; it sets bootloader = "systemd",
    # which bootc's ostree backend cannot install without bootupd, so that
    # setting marks the image as composefs-only too (run 44928280119).
    probe_line = workflow[composefs_probe:workflow.index("\n", composefs_probe)]
    assert '|| grep -Eq "^[[:space:]]*bootloader[[:space:]]*=[[:space:]]*\\"systemd\\""' in probe_line

    # Composefs images install with --composefs-backend (the ostree backend
    # aborts without it, #1215) plus --bootloader systemd to install systemd-boot.
    assert "--composefs-backend --bootloader systemd" in workflow

    # Deployment discovery is backend-aware. /mnt/root is the physical root
    # (bootc's /sysroot), so composefs paths are relative to it: deployments
    # under state/deploy/<id>, the shared /var under state/os/default/var.
    assert 'DEPLOY_DIR="state/deploy"' in workflow
    assert 'STATE_DIR="state"' in workflow
    assert '="sysroot/' not in workflow
    assert 'DEPLOY_DIR="ostree/deploy/default/deploy"' in workflow
    assert 'D="/mnt/root/${DEPLOY_DIR}/${DEPLOY}"' in workflow
    assert 'VAR="/mnt/root/state/os/default/var"' in workflow

    # The ostree-only direct-boot prep (kernel copy, boot.N symlink) is skipped
    # for composefs only. Ostree firmware boot (utah) still runs it, so the
    # vmlinuz/initramfs.img listing after it keeps working.
    prep = workflow.index("Direct kernel boot prep")
    assert workflow.index('if [[ "${COMPOSEFS}" == "true" ]]; then', prep) < workflow.index("KVER=", prep)
    assert 'ls -lh disk.raw vmlinuz initramfs.img' in workflow
    listing = workflow.index("ls -lh disk.raw vmlinuz initramfs.img")
    assert workflow.rindex('if [[ "${COMPOSEFS}" == "true" ]]; then', 0, listing) > workflow.index("sudo umount /mnt/root", prep)

    # The boot partition is created before it is mounted, searched only for
    # composefs, and unmounted again before the loop device is released.
    loader = workflow.index("ENTRY_ROOTS=(/mnt/root/boot/loader/entries)")
    mkdir = workflow.index("sudo mkdir -p /mnt/boot", loader)
    mount = workflow.index('sudo mount "${LOOP}p2" /mnt/boot', loader)
    umount = workflow.index("sudo umount /mnt/boot", loader)
    assert mkdir < mount < umount < workflow.index('sudo losetup -d "${LOOP}"', loader)


def test_e2e_ci_user_tmpfiles_has_no_recursive_home_relabel():
    # A recursive `Z` on the test home walks the runner's Podman storage on
    # every later boot and trips systemd-tmpfiles SELinux denials (#1205).
    workflow = _workflow("e2e.yml")
    start = workflow.index('"${DEP}/etc/tmpfiles.d/"')
    block = workflow[start:workflow.index("ci-user.conf", start)]
    assert "'Z " not in block and "\\nZ " not in block
    assert "d /var/home/bluefin-test 0700" in block
    assert "d /var/home/bluefin-test/.ssh 0700" in block
