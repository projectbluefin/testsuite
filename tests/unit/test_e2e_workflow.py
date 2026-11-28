"""Regression checks for shared E2E workflow setup."""

import subprocess
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


def test_target_step_rewrites_the_composefs_origin_with_the_suite_script():
    # The workflow step and steps.py must point a composefs deployment's origin
    # the same way, since --mutate-in-place is ostree-only (run 44931663470).
    import re

    workflow = _workflow("e2e.yml")
    step = workflow[workflow.index("- name: Point the VM at the target image"):]
    step = step[:step.index("\n      - name:", 1)]
    assert 'if [[ "${COMPOSEFS:-false}" == "true" ]]; then' in step
    assert ".status.booted.composefs.verity // empty" in step
    assert "bootc switch --mutate-in-place" in step  # ostree keeps its path
    point = re.search(r"POINT='(.*)'\n", step).group(1)

    steps = (Path(__file__).resolve().parents[2] / "tests/lifecycle/features/steps/steps.py").read_text()
    body = re.search(r"COMPOSEFS_POINT_ORIGIN = \((.*?)\n\)", steps, re.S).group(1)
    assert point == "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", body)).replace("\\\\", "\\")


def test_composefs_runs_mask_uupd_and_tell_the_runner_the_backend():
    # dakota's uupd staged the target before the suite ran, so every upgrade
    # found "Update already staged" (run 44934532807). Ostree keeps its args.
    workflow = _workflow("e2e.yml")
    guard = workflow.index('KERNEL_ARGS="${KERNEL_ARGS} systemd.mask=uupd.timer systemd.mask=uupd.service"')
    assert workflow.rindex('if [[ "${COMPOSEFS}" == "true" ]]; then', 0, guard) > workflow.index("KERNEL_ARGS=\"root=UUID=")
    assert guard < workflow.index('echo "KERNEL_ARGS=${KERNEL_ARGS}" >> "$GITHUB_ENV"')
    # Both behave invocations receive the backend.
    assert workflow.count('-e COMPOSEFS="${COMPOSEFS:-false}"') == 1
    assert workflow.count('-e COMPOSEFS=\\"${COMPOSEFS:-false}\\"') == 1


def test_chairlift_guest_prep_touches_no_other_suite():
    # #1326: Homebrew setup, a throwaway password and the Homebrew-folder
    # drop-in, for the chairlift suite only. Every added command sits inside
    # this guard, so every other suite's guest is prepared exactly as before.
    workflow = _workflow("e2e.yml")
    guard = 'if [[ "${SUITE_DIR}" == "chairlift" ]]; then'
    assert workflow.count(guard) == 4
    lines = workflow.splitlines()
    guarded = set()
    for start in (i for i, line in enumerate(lines) if line.strip() == guard):
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        end = next(i for i in range(start, len(lines)) if lines[i] == f"{indent}fi")
        guarded.update(range(start, end + 1))
    for number, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if "CHAIRLIFT_PW" in line or "brew-setup.service" in line.replace("systemd.mask=brew-setup.service ", "", 1):
            assert number in guarded, f"line {number + 1} is outside the chairlift guard: {line.strip()}"
        if "CHAIRLIFT_PW" in line and "tee " in line:
            assert line.rstrip().endswith("> /dev/null"), line
    assert 'echo "::add-mask::${CHAIRLIFT_PW}"' in workflow
    assert 'echo "::add-mask::${CHAIRLIFT_PW_HASH}"' in workflow
    assert workflow.index('echo "::add-mask::${CHAIRLIFT_PW_HASH}"') < workflow.index('${CHAIRLIFT_PW_HASH}:|"')
    # The plain text is for the test user alone, and the drop-in is the only
    # unit change.
    assert 'sudo chmod 600 "${VAR}/home/bluefin-test/.config/testsuite/chairlift-admin-password"' in workflow
    assert workflow.count("brew-setup.service.d") == 2
    assert "polkit-1/rules.d" not in workflow

    # The kernel arguments: unchanged for another suite, one mask fewer here.
    kernel_args = next(line.strip() for line in lines if 'KERNEL_ARGS="root=UUID=' in line)
    unmask = 'KERNEL_ARGS="${KERNEL_ARGS/systemd.mask=brew-setup.service /}"'
    assert workflow.index(kernel_args) < workflow.index(unmask) < workflow.index(
        'echo "KERNEL_ARGS=${KERNEL_ARGS}" >> "$GITHUB_ENV"'
    )
    script = (
        f'ROOT_UUID=u; OSTREE_PATH=/p; {kernel_args}; BEFORE="${{KERNEL_ARGS}}"; '
        f'{guard} {unmask}; fi; printf "%s\\n%s\\n" "${{BEFORE}}" "${{KERNEL_ARGS}}"'
    )

    def args_for(suite: str) -> list[str]:
        return subprocess.run(
            ["bash", "-c", script], env={"SUITE_DIR": suite, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()

    before, after = args_for("smoke")
    assert after == before and "systemd.mask=brew-setup.service" in before
    before, after = args_for("chairlift")
    assert after.split() == [arg for arg in before.split() if arg != "systemd.mask=brew-setup.service"]
    assert len(before.split()) - len(after.split()) == 1


def _step_if(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {name}")
    body = []
    for line in lines[start + 1:]:
        if line.strip().startswith("- name:"):
            break
        body.append(line)
    text = "\n".join(body)
    return text[text.index("if:"):text.index("\n        run:") if "\n        run:" in text else None]


def test_chairlift_needs_a_passing_scenario():
    # #1326: behave exits 0 when before_all fails and every scenario is
    # skipped. The daily run reads job success as "passed again", so the
    # assert step must cover chairlift too.
    condition = _step_if(_workflow("e2e.yml"), "Assert suite has passing scenarios")
    assert "env.SUITE_DIR == 'common' || env.SUITE_DIR == 'chairlift') &&" in condition
    assert "steps.run.outputs.behave_rc == '0'" in condition


def test_chairlift_boots_without_the_flatpak_preload():
    # #1326: the suite tests the image as it boots, so the three Flatpak
    # preload steps skip it; every other suite keeps its old condition.
    workflow = _workflow("e2e.yml")
    image = "(contains(inputs.image, '/bluefin') || contains(inputs.image, '/utah') || contains(inputs.image, 'dakota'))"
    suites = "steps.shard.outputs.suite_dir != 'lifecycle' && steps.shard.outputs.suite_dir != 'chairlift'"
    for name in ("Restore Flatpak download cache", "Install cached Flatpaks in VM"):
        assert f"if: ${{{{ {image} && {suites} }}}}" in _step_if(workflow, name)
    prime = _step_if(workflow, "Prime Flatpak download cache")
    assert f"if: ${{{{ {image} && {suites} && steps.flatpak-cache.outputs.cache-hit != 'true' }}}}" in prime
    assert workflow.count("steps.shard.outputs.suite_dir != 'chairlift'") == 3
