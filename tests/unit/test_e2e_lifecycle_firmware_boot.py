"""The lifecycle suite boots through OVMF and the image's own loader (#1023).

A direct -kernel boot reboots into the first deployment's kernel, so upgrade
and rollback scenarios never reached the staged deployment.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _steps() -> dict[str, dict]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "e2e.yml").read_text())
    return {step.get("name"): step for step in workflow["jobs"]["e2e"]["steps"]}


def test_only_the_lifecycle_job_installs_ovmf():
    packages = _steps()["Free disk space"]["with"]["apt-packages"]
    assert packages == ("${{ matrix.suite == 'lifecycle' && 'qemu-system-x86 ovmf' "
                        "|| 'qemu-system-x86' }}")


def test_lifecycle_install_keeps_the_images_own_loader_and_needs_it():
    install = _steps()["Install OCI image and configure disk"]["run"]
    lifecycle = install.index('if [[ "${SUITE_DIR}" == "lifecycle" ]]')
    probe = install.index("command -v bootupctl", lifecycle)
    firmware = install.index("FIRMWARE_BOOT=true", lifecycle)
    override = install.index('BOOTLOADER_FLAG="--bootloader systemd"')
    # Firmware boot needs bootupd in the image; the systemd-boot override
    # applies only when firmware boot is off (other suites, or an ostree
    # lifecycle image without bootupd, run 43525356388). Composefs images
    # such as dakota get firmware boot automatically (#1215).
    assert lifecycle < probe < firmware < override
    guard = install.index('if [[ "${FIRMWARE_BOOT}" != "true" ]]')
    assert firmware < guard < override
    assert "has neither a composefs backend nor bootupctl" in install
    fatal = install.index('if [[ ${BOOTC_INSTALL_RC} -ne 0 && "${FIRMWARE_BOOT}" == "true" ]]; then')
    assert fatal < install.index("continuing with direct kernel boot")
    assert "has no -kernel fallback" in install[fatal:fatal + 400]
    assert 'echo "FIRMWARE_BOOT=${FIRMWARE_BOOT}" >> "$GITHUB_ENV"' in install


def test_lifecycle_kernel_args_go_on_the_loader_entries_without_relabelling():
    install = _steps()["Install OCI image and configure disk"]["run"]
    start = install.index("# shellcheck disable=SC2086 # split KERNEL_ARGS")
    block = install[start:install.index("\nfi\n", start)]
    assert "grep -vE '^(root=|rw$|ostree=)'" in block  # bootc already wrote these
    assert "/mnt/root/boot/loader/entries" in block and "no loader entries" in block
    # tee rewrites in place, keeping each entry's SELinux label; sed -i would not.
    assert 'sudo tee "${ENTRY}"' in block and "sed -i" not in block
    # The same KERNEL_ARGS the direct boot uses, computed once.
    assert install.index('echo "KERNEL_ARGS=${KERNEL_ARGS}" >> "$GITHUB_ENV"') < install.index(block)


def test_lifecycle_boots_through_ovmf_with_no_kernel_boot():
    boot = _steps()["Boot VM with QEMU + KVM"]["run"]
    firmware = boot[boot.index('if [[ "${FIRMWARE_BOOT}" == "true" ]]; then'):boot.index("sudo qemu-system-x86_64")]
    assert "cp /usr/share/OVMF/OVMF_VARS_4M.fd ./ovmf-vars.fd" in firmware
    assert "OVMF_CODE_4M.fd,readonly=on" in firmware
    assert "-kernel" not in firmware and "-append" not in firmware
    assert '"${BOOT_ARGS[@]}"' in boot
    # Other suites keep the direct kernel boot unchanged.
    assert 'BOOT_ARGS=(-kernel ./vmlinuz -initrd ./initramfs.img -append "${KERNEL_ARGS}")' in boot


def test_reboot_waits_long_enough_for_a_firmware_boot():
    steps = (ROOT / "tests/lifecycle/features/steps/steps.py").read_text()
    assert "REBOOT_DEADLINE_S = 300" in steps
    assert "deadline = time() + REBOOT_DEADLINE_S" in steps


def test_manual_runs_can_stage_an_upgrade_target():
    # Lets a maintainer prove an upgrade on a branch: boot the previous build,
    # stage the candidate, run the lifecycle suite.
    manual = yaml.safe_load((ROOT / ".github" / "workflows" / "manual.yml").read_text())
    assert manual[True]["workflow_dispatch"]["inputs"]["target_image"]["default"] == ""
    assert manual["jobs"]["test"]["with"]["target-image"] == "${{ github.event.inputs.target_image }}"
