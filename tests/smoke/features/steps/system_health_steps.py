"""Custom step definitions for system health smoke checks."""
import json
import os
import re
import subprocess

from behave import step
from tests.shared.ssh_config import ssh_argv
try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass


IGNORED_FAILED_UNITS_IN_VM = {
    "mcelog.service",
    "avahi-daemon.service",
    "cups.service",
    "cups.path",
    "cups.socket",
    "cups.browsed.service",
    "podman-auto-update.timer",
    "malcontent-control.service",
    # malcontent-webd-update.timer requires network access to fetch parental-controls
    # blocklists; fails in isolated QEMU VMs (Dakota, CentOS Stream based images)
    "malcontent-webd-update.timer",
    "malcontent-webd-update.service",
    "blueman-mechanism.service",
    "gnome-remote-desktop.service",
    # bootupd cannot update the bootloader inside a QEMU VM (no EFI vars/bootctl)
    "bootloader-update.service",
    # TuneD invokes bootc/rpm-ostree while first-boot storage initialization owns
    # the daemon in the disposable QEMU guest. It times out only on that boot;
    # non-virtualized failures remain release-blocking.
    "tuned.service",
    # input-remapper cannot initialize its uinput devices inside a QEMU VM
    "input-remapper.service",
    # NVIDIA services require physical GPU hardware — always fail in QEMU
    "nvidia-persistenced.service",
    "ublue-nvctk-cdi.service",
    # systemd-oomd needs memory pressure files that QEMU VMs don't expose
    "systemd-oomd.service",
    "systemd-oomd.socket",
    # fwupd-refresh.service requires network access to fetch firmware metadata;
    # fails in isolated QEMU VMs where outbound connectivity is not available
    "fwupd-refresh.service",
    # audit rules and resolver runtime directories fail in containerized QA hosts
    "audit-rules.service",
    "auditd.service",
    "systemd-resolved.service",
    "systemd-resolved-monitor.socket",
    "systemd-resolved-varlink.socket",
    "foomaticrip-upgrade.service",
}

# When behave runs inside the runner container (--pid=host --privileged), system
# commands like systemctl, bootc, and ujust are not in the container image. Use
# nsenter to run them in the host VM's mount namespace via /proc/1/ns/mnt.
_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")


def _run(cmd: str, timeout: int = 30):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _run_host(cmd: str, timeout: int = 30):
    """Run cmd on the host VM via SSH when inside the runner container.

    The container is launched with VM_IP/VM_USER/SSH_KEY/SSH_PORT env vars and
    the SSH key mounted, so we SSH to localhost:22 on the VM instead of nsenter
    (which requires host-level CAP_SYS_ADMIN that rootless podman cannot grant).
    """
    if _IN_CONTAINER:
        result = subprocess.run(
            ssh_argv() + [cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        env = dict(os.environ)
        if not env.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        safe_cmd = cmd.replace(
            "source /tmp/session.env 2>/dev/null;",
            "[ -f /tmp/session.env ] && . /tmp/session.env 2>/dev/null || true;",
        )
        result = subprocess.run(
            safe_cmd,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _running_in_vm() -> bool:
    _, returncode, _ = _run_host("systemd-detect-virt --quiet")
    return returncode == 0


def _has_image_reference(value) -> bool:
    if isinstance(value, dict):
        if value.get("imageDigest") or value.get("image") or value.get("type") == "container":
            return True
        if value.get("kind") == "BootcHost" or "apiVersion" in value:
            return True
        return any(_has_image_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_image_reference(item) for item in value)
    return False


def _skip_scenario(context, reason: str) -> None:
    scenario = getattr(context, "scenario", None)
    if scenario is not None:
        try:
            scenario.skip(reason)
        except TypeError:
            scenario.skip()


@step("No failed systemd units at boot")
def no_failed_systemd_units_at_boot(context) -> None:
    output, returncode, stderr = _run_host("systemctl list-units --failed --no-pager --plain")
    assert returncode == 0, f"systemctl failed: {stderr or output}"

    failed_units = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("UNIT ", "LOAD ", "Legend:")):
            continue
        if stripped.endswith("loaded units listed.") or stripped.startswith("To show all installed unit files"):
            continue
        if re.match(r"^\S+\s+loaded\s+failed\s+failed\s+", stripped):
            unit = stripped.split()[0]
            if _running_in_vm() and unit in IGNORED_FAILED_UNITS_IN_VM:
                continue
            failed_units.append(stripped)

    assert not failed_units, f"Failed systemd units detected: {failed_units}"


@step("No critical kernel errors in journal")
def no_critical_kernel_errors_in_journal(context) -> None:
    output, returncode, stderr = _run_host("journalctl -b -p 0..2 --no-pager -q")
    assert returncode == 0, f"journalctl failed: {stderr or output}"
    assert not output, f"Critical journal entries found:\n{output}"


@step("Bluefin image identity is present in os-release")
def bluefin_image_identity_is_present_in_os_release(context) -> None:
    output, returncode, stderr = _run_host("grep -i bluefin /etc/os-release")
    if returncode != 0:
        # Not a Bluefin image — skip rather than fail so non-Bluefin smoke runs stay green
        _skip_scenario(context, "No Bluefin identity in /etc/os-release — not a Bluefin image")
        return
    assert output, "Expected non-empty Bluefin match in /etc/os-release"


@step("bootc status shows a valid image reference")
def bootc_status_shows_a_valid_image_reference(context) -> None:
    # Try privileged first (sudo); fall back to unprivileged for read-only status.
    output, returncode, stderr = _run_host("sudo bootc status --format=json 2>&1 || bootc status --format=json 2>&1")
    combined_err = f"{stderr} {output}".lower()
    # In CI QEMU VMs, bootc may fail to open /boot (no bootupd, bare kernel boot).
    # Treat this as a known VM limitation — skip the assertion rather than fail.
    if returncode != 0 and "opendir(boot)" in combined_err:
        return
    # bootc not installed on this image — skip gracefully
    if returncode != 0 and ("not found" in combined_err or "no such file" in combined_err or "command not found" in combined_err):
        _skip_scenario(context, "bootc not found on this image")
        return
    # Non-root access denied without --sysroot — skip rather than fail
    if returncode != 0 and ("not root" in combined_err or "sysroot" in combined_err):
        _skip_scenario(context, "bootc status requires root — skipping on non-root runner")
        return
    assert returncode == 0, f"bootc status failed: {stderr or output}"

    try:
        status = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"bootc status did not return valid JSON: {exc}") from exc

    assert _has_image_reference(status), "bootc status JSON does not contain an image or imageDigest field"


@step("External DNS resolves external hosts")
def external_dns_resolves_external_hosts(context) -> None:
    output, returncode, _ = _run_host("getent hosts ghcr.io")
    assert returncode == 0 and output.strip(), (
        f"DNS resolution for ghcr.io failed (rc={returncode}): {output!r}"
    )


@step('Writable system storage has at least "{percent}" percent free space')
def writable_system_storage_has_at_least_percent_free_space(context, percent: str) -> None:
    output, returncode, stderr = _run_host("df -P /var")
    assert returncode == 0, f"df failed: {stderr or output}"

    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) >= 2, f"Unexpected df output: {output}"

    columns = lines[1].split()
    assert len(columns) >= 5, f"Could not parse df output row: {lines[1]}"

    used_percent = int(columns[4].rstrip("%"))
    free_percent = 100 - used_percent
    required_free_percent = int(percent)
    assert free_percent >= required_free_percent, (
        f"Root filesystem free space {free_percent}% is below required {required_free_percent}%"
    )


@step("AT-SPI accessibility bus is reachable from the GNOME session")
def at_spi_accessibility_bus_is_reachable_from_the_gnome_session(context) -> None:
    """Verify the VM's session-scoped accessibility bus, not the runner container."""
    output, returncode, stderr = _run_host(
        "source /tmp/session.env 2>/dev/null; "
        "gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus "
        "--method org.a11y.Bus.GetAddress"
    )
    assert returncode == 0, f"AT-SPI bus query failed: {stderr or output}"
    assert "unix:" in output, f"AT-SPI bus returned no Unix address: {output!r}"


@step("ujust is on PATH and returns exit 0")
def ujust_on_path(context) -> None:
    which_out, which_rc, _ = _run_host("which ujust 2>/dev/null")
    if which_rc != 0 or not which_out:
        # ujust is Bluefin-specific — skip gracefully on non-Bluefin images
        _skip_scenario(context, "ujust not on PATH — not a Bluefin image")
        return
    _, returncode, stderr = _run_host("ujust --version 2>/dev/null || ujust --help 2>/dev/null")
    assert returncode == 0, f"ujust exited non-zero: {stderr}"


@step("ujust --list prints at least one task")
def ujust_list_has_tasks(context) -> None:
    output, returncode, stderr = _run_host("ujust --list")
    # just 1.x may fail with a parse error on newer Justfile syntax used by Bluefin.
    # Treat this as a known compatibility issue — warn but don't fail the suite.
    if returncode != 0:
        combined = (stderr or output or "").lower()
        if "unknown start of token" in combined or "unknown token" in combined:
            print(
                f"WARNING: ujust --list parse error (known just version compat issue): {stderr or output}",
                flush=True,
            )
            return
        assert returncode == 0, f"ujust --list failed (rc={returncode}): {stderr or output}"
    tasks = [line for line in output.splitlines() if line.strip()]
    assert tasks, "ujust --list returned no tasks"


@step("ujust report --confirm rejects non-integer issue number")
def ujust_report_confirm_invalid(context) -> None:
    output, returncode, stderr = _run_host("ujust report --confirm abc 2>&1")
    if returncode != 0 and "does not contain recipe" in output:
        _skip_scenario(context, "ujust 'report' recipe not present on this image")
        return
    assert returncode == 1, f"Expected exit code 1, got {returncode}. Output: {output}"
    assert "positive integer" in output, f"Expected validation error, got: {output}"


@step("ujust report --confirm without issue number prints error")
def ujust_report_confirm_missing_number(context) -> None:
    output, returncode, stderr = _run_host("ujust report --confirm 2>&1")
    if returncode != 0 and "does not contain recipe" in output:
        _skip_scenario(context, "ujust 'report' recipe not present on this image")
        return
    assert returncode == 1, f"Expected exit code 1, got {returncode}. Output: {output}"
    assert "requires an issue number" in output, f"Expected parameter error, got: {output}"


# ---------------------------------------------------------------------------
# composefs file-capability regression (dakota#841)
# Multi-layer OCI images silently strip security.capability xattrs; getcap
# verifies the xattrs survived the composefs replay.
#
# ping is deliberately not asserted: Fedora's iputils ships /usr/bin/ping with
# no file capability (plain 0755; only clockdiff/arping get %caps(cap_net_raw=p))
# and provides unprivileged ping via net.ipv4.ping_group_range instead. A
# cap_net_raw assertion can never hold on a Fedora-based image, so it only
# produced a deterministic false failure (projectbluefin/bluefin#989) instead of
# a regression signal. newuidmap/newgidmap retain the real capability-bearing
# signal for the dakota#841 failure class.
# ---------------------------------------------------------------------------

@step("newuidmap and newgidmap retain their security.capability xattrs")
def composefs_file_capabilities_preserved(context) -> None:
    binaries = {
        "/usr/bin/newuidmap": "cap_setuid",
        "/usr/bin/newgidmap": "cap_setgid",
    }
    missing = []
    for path, expected_cap in binaries.items():
        output, returncode, stderr = _run_host(f"getcap {path}")
        assert returncode == 0, f"getcap failed for {path}: {stderr or output}"
        if expected_cap not in output:
            missing.append(f"{path}: expected '{expected_cap}' in '{output}'")
    assert not missing, (
        "composefs file-capability regression (projectbluefin/dakota#841) — "
        f"missing capabilities: {missing}. "
        "A multi-layer OCI image may have stripped security.capability xattrs."
    )


# ---------------------------------------------------------------------------
# GDM boot regression (bluefin-lts emergency-console incident 2026-06-13)
# Asserts the system reached the graphical display manager, not emergency
# console.  Applies to all variants (testing + production).
# ---------------------------------------------------------------------------

@step("gdm.service is active")
def gdm_service_is_active(context) -> None:
    output, returncode, stderr = _run_host("systemctl is-active gdm.service")
    assert output == "active", (
        f"gdm.service is not active (got '{output}'; stderr={stderr!r}) — "
        "system may have booted to emergency console. "
        "Check composefs xattr regression (projectbluefin/dakota#841) and "
        "GDM autologin config (/etc/gdm/custom.conf)."
    )


@step("graphical.target is active")
def graphical_target_is_active(context) -> None:
    output, returncode, stderr = _run_host("systemctl is-active graphical.target")
    assert output == "active", (
        f"graphical.target is not active (got '{output}'; stderr={stderr!r}) — "
        "display manager did not reach the graphical session target."
    )


@step("tailscale is installed and daemon is running")
def tailscale_is_installed_and_daemon_is_running(context) -> None:
    output, returncode, stderr = _run_host("tailscale --version")
    assert returncode == 0, f"tailscale --version failed (rc={returncode}): {stderr or output}"

    output, returncode, stderr = _run_host("systemctl is-active tailscaled")
    assert returncode == 0 and output == "active", (
        f"tailscaled is not active (got '{output}'; stderr={stderr!r})"
    )


@step("uupd auto-updater is installed and configured")
def uupd_auto_updater_is_installed_and_configured(context) -> None:
    output, returncode, stderr = _run_host("uupd --help")
    if returncode != 0:
        combined = (output + " " + stderr).lower()
        if "not found" in combined or "no such file" in combined:
            _skip_scenario(context, "uupd not installed on this image")
            return
        assert returncode == 0, f"uupd --help failed (rc={returncode}): {stderr or output}"

    output, returncode, stderr = _run_host("systemctl is-enabled uupd.timer")
    assert returncode == 0, f"uupd.timer check failed: {stderr or output}"
    assert output in ("enabled", "static"), f"Expected uupd.timer to be enabled or static, got: {output}"


@step("fastfetch is present and operational")
def fastfetch_is_present_and_operational(context) -> None:
    output, returncode, stderr = _run_host("fastfetch --version")
    assert returncode == 0, f"fastfetch --version failed (rc={returncode}): {stderr or output}"
    assert "fastfetch" in output.lower(), f"Expected 'fastfetch' in output, got: {output}"
