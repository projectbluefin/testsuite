"""Custom step definitions for GNOME notification smoke tests."""
import os
import re
import subprocess
from time import sleep

from behave import step
from tests.shared.ssh_config import ssh_argv
try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")


def _run(cmd: str):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _run_host(cmd: str):
    """Run cmd on the host VM via SSH when inside the runner container."""
    if _IN_CONTAINER:
        result = subprocess.run(
            ssh_argv() + [cmd],
            capture_output=True, text=True, timeout=30,
        )
    else:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _parse_notification_id(output: str) -> int:
    match = re.search(r"\(uint32\s+(\d+),\)", output)
    assert match is not None, f"Could not parse notification ID from gdbus output: {output!r}"
    return int(match.group(1))


@step("A test desktop notification is sent via gdbus")
def send_test_desktop_notification(context) -> None:
    output, returncode, stderr = _run(
        "gdbus call --session "
        "--dest org.freedesktop.Notifications "
        "--object-path /org/freedesktop/Notifications "
        "--method org.freedesktop.Notifications.Notify "
        "'' 0 '' 'Test Notification' 'Testsuite notification body' '[]' '{}' 3000"
    )
    if returncode != 0:
        combined = (stderr + output).lower()
        if any(p in combined for p in ("machine-id", "cannot spawn", "error connecting", "no such file")):
            print(
                f"WARNING: gdbus notification skipped — D-Bus session bus unavailable "
                f"in container environment: {stderr or output}",
                flush=True,
            )
            try:
                context.scenario.skip("D-Bus session bus not reachable from container — skipping notification test")
            except Exception:  # noqa: BLE001
                pass
            context.notification_id = None
            return
    assert returncode == 0, f"gdbus notification send failed: {stderr or output}"
    context.notification_gdbus_output = output
    context.notification_id = _parse_notification_id(output)
    sleep(0.3)


@step("Notification request returns a positive notification ID")
def notification_request_returns_positive_id(context) -> None:
    notification_id = getattr(context, "notification_id", None)
    if notification_id is None:
        return  # scenario was already skipped in send_test_desktop_notification
    assert notification_id > 0, f"Expected notification ID > 0, got {notification_id}"


@step("Dismiss the notification via gdbus CloseNotification")
def dismiss_notification_via_gdbus(context) -> None:
    notification_id = getattr(context, "notification_id", None)
    assert notification_id is not None, (
        "No notification ID captured — run 'A test desktop notification is sent via gdbus' first"
    )
    _, returncode, stderr = _run(
        f"gdbus call --session "
        f"--dest org.freedesktop.Notifications "
        f"--object-path /org/freedesktop/Notifications "
        f"--method org.freedesktop.Notifications.CloseNotification "
        f"{notification_id}"
    )
    assert returncode == 0, f"CloseNotification failed for id={notification_id}: {stderr}"


# True once no notification banner is on screen. The banner ref goes null
# when Shell finishes the dismiss animation (GNOME 50 may keep it but hidden).
# Do not also require Main.messageTray._bannerBin to be hidden: on GNOME 51
# the bin stays visible with no banner in it, so that check never passed and
# the step only ever "passed" through a force-dismiss and a warning, whether or
# not CloseNotification worked (#827 audit row 10, probe 3).
BANNER_GONE_JS = (
    "(Main.messageTray._banner === null || "
    "Main.messageTray._banner === undefined || "
    "!Main.messageTray._banner.visible).toString()"
)
BANNER_DISMISS_TIMEOUT_S = 20  # GNOME 50 banners can linger in QEMU


def _banner_gone(run=subprocess.run) -> tuple[bool, str]:
    import re

    result = run(
        ["gdbus", "call", "--session",
         "--dest", "org.gnome.Shell",
         "--object-path", "/org/gnome/Shell",
         "--method", "org.gnome.Shell.Eval",
         BANNER_GONE_JS],
        capture_output=True, text=True, timeout=5,
    )
    out = result.stdout
    m = re.search(r",\s*'\"?(true|false)\"?'\s*\)", out, re.IGNORECASE)
    return bool(m and m.group(1).lower() == "true"), out


@step("Notification banner is no longer showing via Shell.Eval")
def notification_banner_no_longer_showing(context, run=subprocess.run, pause=sleep) -> None:
    last_out = ""
    for _ in range(BANNER_DISMISS_TIMEOUT_S * 2):
        gone, last_out = _banner_gone(run)
        if gone:
            return
        pause(0.5)
    raise AssertionError(
        f"Notification banner still showing {BANNER_DISMISS_TIMEOUT_S}s after "
        f"CloseNotification; Shell.Eval returned: {last_out!r}"
    )


@step("No gnome-shell notification journal errors are present")
def no_gnome_shell_notification_journal_errors(context) -> None:
    output, returncode, stderr = _run_host("journalctl --no-pager -b -p err..emerg --lines=200")
    assert returncode == 0, f"journalctl failed: {stderr or output}"

    pattern = re.compile(r"gnome-shell.*notif", re.IGNORECASE)
    matches = [line for line in output.splitlines() if pattern.search(line)]
    assert not matches, f"Unexpected gnome-shell notification journal errors: {matches}"
