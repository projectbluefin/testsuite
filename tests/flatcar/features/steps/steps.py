"""
Step definitions for Flatcar boot and lifecycle tests.

Steps issue SSH commands to the Flatcar VM via subprocess.
Connection details come from context (set in environment.py before_all).

No qecore, no dogtail — plain behave.
"""
import subprocess
import time

from behave import step

from tests.shared.ssh_config import ssh_argv
from tests.shared.ssh_steps import *  # noqa: F401,F403,F405
from tests.shared.ssh_steps import run_ssh, ssh_output_is, ssh_return_code_is  # noqa: F401

# Flatcar stores its update client configuration here. Ignition/Butane writes
# this file, and `flatcar-update` edits it in place.
UPDATE_CONF = "/etc/flatcar/update.conf"
UPDATE_CONF_BACKUP = "/etc/flatcar/update.conf.testsuite-backup"

# GRUB deletes this ESP marker only after Ignition completes successfully.
# See https://www.flatcar.org/docs/latest/fb-provision/ignition/
FIRST_BOOT_MARKER = "/boot/flatcar/first_boot"

# Upstream's supported way to permanently disable automatic updates is to point
# the update client at an invalid server, not to mask update-engine.
# See https://www.flatcar.org/docs/latest/updates-releases/releases/update-strategies/
DISABLED_SERVER_VALUES = frozenset({"disabled", "off", "none", ""})


def parse_update_conf(text):
    """Parse Flatcar's ``/etc/flatcar/update.conf`` into a dict.

    The file is a shell-sourced ``KEY=VALUE`` fragment. Values may be quoted,
    blank lines and ``#`` comments are ignored, and later assignments win
    (matching shell sourcing semantics).
    """
    settings = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        settings[key] = value
    return settings


def automatic_updates_disabled(text):
    """Return True when ``update.conf`` disables automatic updates.

    Flatcar disables automatic updates by overwriting ``SERVER`` with an
    invalid value; ``SERVER=disabled`` is the value ``flatcar-update
    --disable-afterwards`` writes.
    """
    settings = parse_update_conf(text)
    if "SERVER" not in settings:
        return False
    return settings["SERVER"].strip().lower() in DISABLED_SERVER_VALUES


@step("Flatcar VM is reachable over SSH")
def flatcar_vm_is_reachable(context) -> None:
    last_error = ''
    for _ in range(6):
        stdout, returncode = run_ssh(context, "echo ok", timeout=20)
        stderr = getattr(getattr(context, "last_ssh_result", None), "stderr", "")
        if returncode == 0 and stdout == "ok":
            return
        last_error = stderr or stdout
        time.sleep(5)
    raise AssertionError(f"Cannot reach Flatcar VM at {context.vm_ip}: {last_error}")


@step("Install Flatcar to target disk via knuckle")
def install_flatcar_to_target_disk_via_knuckle(context) -> None:
    stdout, returncode = run_ssh(
        context,
        "echo '{}' | sudo knuckle headless --config - --target /dev/vdb",
        timeout=300,
    )
    stderr = getattr(getattr(context, "last_ssh_result", None), "stderr", "")
    assert returncode == 0, (
        "Flatcar install via knuckle failed\n"
        f"stdout: {stdout}\n"
        f"stderr: {stderr}"
    )


@step("Reboot VM from target disk")
def reboot_vm_from_target_disk(context) -> None:
    # TODO: This is best-effort only; the runner cannot yet verify that the VM
    # actually switched its boot device before reconnecting over SSH.
    reboot_command = (
        "sudo systemctl reboot || sudo reboot || sudo shutdown -r now"
    )
    try:
        subprocess.run(
            ssh_argv(context, quiet=True) + [reboot_command],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        pass

    saw_disconnect = False
    disconnect_deadline = time.time() + 60
    while time.time() < disconnect_deadline:
        try:
            stdout, returncode = run_ssh(context, "echo ok", timeout=15)
        except subprocess.TimeoutExpired:
            saw_disconnect = True
            break

        if returncode != 0:
            saw_disconnect = True
            break

        time.sleep(5)

    reconnect_deadline = time.time() + 120
    while time.time() < reconnect_deadline:
        try:
            stdout, returncode = run_ssh(context, "echo ok", timeout=15)
        except subprocess.TimeoutExpired:
            time.sleep(5)
            continue

        if returncode == 0 and stdout == "ok":
            return

        if not saw_disconnect:
            saw_disconnect = returncode != 0
        time.sleep(5)

    raise AssertionError(
        f"Flatcar VM at {context.vm_ip} did not come back after reboot attempt"
    )


@step("Flatcar target disk has partitions")
def flatcar_target_disk_has_partitions(context) -> None:
    run_ssh(context, "lsblk -ln -o TYPE /dev/vdb | grep -c '^part$'")
    ssh_return_code_is(context, "0")
    assert getattr(context, "command_stdout", "").strip() != "0", (
        "Expected /dev/vdb to contain at least one partition after knuckle install"
    )


@step('Ignition hostname is "{expected}"')
def ignition_hostname_is(context, expected) -> None:
    run_ssh(context, "cat /etc/hostname")
    ssh_return_code_is(context, "0")
    ssh_output_is(context, expected)


@step("Flatcar ESP is mounted at /boot")
def flatcar_esp_is_mounted_at_boot(context) -> None:
    """Guard against false passes in the first-boot marker assertion.

    ``/boot/flatcar/first_boot`` living on an unmounted directory would make an
    absence check trivially true, so confirm the EFI System Partition (always
    FAT) is really mounted there first.
    """
    run_ssh(context, "findmnt -no FSTYPE /boot")
    ssh_return_code_is(context, "0")
    fstype = getattr(context, "command_stdout", "").strip().lower()
    assert fstype.startswith("vfat"), (
        f"Expected the EFI System Partition (vfat) mounted at /boot, found {fstype!r}"
    )


@step("Ignition first-boot marker is cleared")
def ignition_first_boot_marker_is_cleared(context) -> None:
    """Assert Ignition completed successfully on first boot.

    GRUB sets ``flatcar.first_boot=detected`` when the ESP contains
    ``flatcar/first_boot``, and that marker is deleted only after Ignition runs
    successfully. A marker still present on a booted system means Ignition
    either did not run or did not complete.
    """
    run_ssh(context, f"test -e {FIRST_BOOT_MARKER}")
    assert getattr(context, "ssh_rc", 0) != 0, (
        f"{FIRST_BOOT_MARKER} still exists — Ignition did not complete on first boot"
    )


@step("Ignition-provisioned SSH keys are present for the test user")
def ignition_provisioned_ssh_keys_are_present(context) -> None:
    """Assert the provisioned user has the SSH keys Ignition wrote.

    Flatcar writes ``passwd.users[].sshAuthorizedKeys`` either straight to
    ``~/.ssh/authorized_keys`` or, on images still using ``update-ssh-keys``,
    to a fragment under ``~/.ssh/authorized_keys.d/``. Accept either shape and
    assert on the return code so no output format is assumed.
    """
    run_ssh(
        context,
        'test -s "$HOME/.ssh/authorized_keys" '
        '|| find "$HOME/.ssh/authorized_keys.d" -type f -size +0c -print -quit '
        '| grep -q .',
    )
    ssh_return_code_is(context, "0")


@step("Flatcar update config is backed up")
def flatcar_update_config_is_backed_up(context) -> None:
    run_ssh(context, f"sudo cp -a {UPDATE_CONF} {UPDATE_CONF_BACKUP}")
    ssh_return_code_is(context, "0")
    context.update_conf_backed_up = True


@step("Automatic updates are disabled via update.conf")
def automatic_updates_are_disabled(context) -> None:
    """Apply Flatcar's supported disable switch: ``SERVER=disabled``."""
    run_ssh(
        context,
        f"sudo sed -i '/^[[:space:]]*SERVER=/d' {UPDATE_CONF} "
        f"&& echo 'SERVER=disabled' | sudo tee -a {UPDATE_CONF} >/dev/null",
    )
    ssh_return_code_is(context, "0")


@step("Flatcar automatic updates are reported as disabled")
def flatcar_automatic_updates_are_reported_as_disabled(context) -> None:
    run_ssh(context, f"cat {UPDATE_CONF}")
    ssh_return_code_is(context, "0")
    conf = getattr(context, "command_stdout", "")
    assert automatic_updates_disabled(conf), (
        f"Expected {UPDATE_CONF} to disable automatic updates via SERVER, got:\n{conf}"
    )


@step("update-engine restarts cleanly")
def update_engine_restarts_cleanly(context) -> None:
    """Disabling updates must not break the unit.

    Upstream explicitly recommends the ``SERVER`` override over masking
    ``update-engine``, precisely so manual updates stay possible.
    """
    run_ssh(context, "sudo systemctl restart update-engine", timeout=120)
    ssh_return_code_is(context, "0")
    run_ssh(context, "systemctl is-active update-engine")
    ssh_output_is(context, "active")


@step("Flatcar update config is restored")
def flatcar_update_config_is_restored(context) -> None:
    restore_update_conf(context)


def restore_update_conf(context) -> None:
    """Restore ``update.conf`` from the backup, if one was taken.

    Called both by the explicit Gherkin step and by ``after_scenario`` so a
    mid-scenario failure cannot leave the VM with updates disabled.
    """
    if not getattr(context, "update_conf_backed_up", False):
        return
    run_ssh(
        context,
        f"sudo test -e {UPDATE_CONF_BACKUP} "
        f"&& sudo mv -f {UPDATE_CONF_BACKUP} {UPDATE_CONF} "
        f"&& sudo systemctl restart update-engine",
        timeout=120,
    )
    context.update_conf_backed_up = False
    ssh_return_code_is(context, "0")


@step("Flatcar update channel is configured")
def flatcar_update_channel_is_configured(context) -> None:
    run_ssh(
        context,
        "grep -E '^GROUP=' /etc/flatcar/update.conf 2>/dev/null",
    )
    ssh_return_code_is(context, "0")
    assert getattr(context, "command_stdout", "").strip(), (
        "Expected /etc/flatcar/update.conf to contain a non-empty GROUP setting"
    )


@step("Afterburn service is available")
def afterburn_service_is_available(context) -> None:
    run_ssh(
        context,
        "systemctl status afterburn 2>&1 | grep -c 'active\\|inactive'",
    )
    ssh_return_code_is(context, "0")
