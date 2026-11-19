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
    # composefs backend forces the firmware-boot path (no bootupd to use).
    assert "grep -lq composefs-backend /usr/lib/bootc/install/*.toml" in workflow
    assert (
        'if [[ "${COMPOSEFS}" == "true" ]]; then\n'
        "            FIRMWARE_BOOT=true"
    ) in workflow

    # Composefs images install with --composefs-backend (the ostree backend
    # aborts without it, #1215) plus --bootloader systemd to install systemd-boot.
    assert "--composefs-backend --bootloader systemd" in workflow

    # Deployment discovery is backend-aware: composefs deployments live under
    # /sysroot/state/deploy/<id>, not /ostree/deploy/default/deploy.
    assert 'DEPLOY_DIR="sysroot/state/deploy"' in workflow
    assert 'DEPLOY_DIR="ostree/deploy/default/deploy"' in workflow
    assert 'D="/mnt/root/${DEPLOY_DIR}/${DEPLOY}"' in workflow

    # The ostree-only direct-boot prep (kernel extraction, boot.N symlink,
    # ostree= arg) must not run for firmware boot, or it would write a bogus
    # /ostree/ tree onto the composefs deployment.
    assert "Direct kernel boot prep" in workflow
    assert 'if [[ "${FIRMWARE_BOOT}" == "true" ]]; then' in workflow


def test_e2e_ci_user_tmpfiles_has_no_recursive_home_relabel():
    # A recursive `Z` on the test home walks the runner's Podman storage on
    # every later boot and trips systemd-tmpfiles SELinux denials (#1205).
    workflow = _workflow("e2e.yml")
    start = workflow.index('"${DEP}/etc/tmpfiles.d/"')
    block = workflow[start:workflow.index("ci-user.conf", start)]
    assert "'Z " not in block and "\\nZ " not in block
    assert "d /var/home/bluefin-test 0700" in block
    assert "d /var/home/bluefin-test/.ssh 0700" in block
