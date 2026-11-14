"""Custom step definitions for GNOME notification smoke tests."""
import os
import re
import subprocess
from time import sleep

from behave import step
from tests.shared.ssh_config import ssh_argv

# Summary of the notification the smoke scenarios send and dismiss.
TEST_NOTIFICATION_TITLE = "Test Notification"

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
        f"'' 0 '' '{TEST_NOTIFICATION_TITLE}' 'Testsuite notification body' '[]' '{{}}' 3000"
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


# True once the test notification is gone: not the visible banner and not in
# the message tray. Do not test "no banner at all": GNOME Shell holds a banner
# on screen while the session is idle, and a headless VM is always idle, so an
# unrelated earlier banner ("Settings") stayed up for minutes after our
# notification was already closed. The GNOME 50 version also required
# Main.messageTray._bannerBin hidden, which GNOME 51 never does with no banner
# in it, so it only ever "passed" through a force-dismiss and a warning, closed
# or not (#827 audit row 10, probe 3: our notification leaves the tray at once;
# the held banner clears ~2 s after any input).
BANNER_GONE_JS = (
    "(() => { const t = Main.messageTray; const title = '" + TEST_NOTIFICATION_TITLE + "';"
    " const b = t._banner;"
    " const shown = !!(b && b.visible && b.notification && b.notification.title === title);"
    " let queued = false;"
    " try { queued = t.getSources().some(s => s.notifications.some(n => n.title === title)); }"
    " catch (e) { queued = false; }"
    " let idle = null;"
    " try { idle = global.backend.get_core_idle_monitor().get_idletime(); } catch (e) {}"
    " return JSON.stringify({ gone: !shown && !queued, shown: shown, queued: queued,"
    "  banner: b ? ((b.notification && b.notification.title) || '?') : null,"
    "  destroyed: !!(b && b.notification && b.notification._destroyed), idle_ms: idle }); })()"
)
BANNER_DISMISS_TIMEOUT_S = 20  # GNOME 50 banners can linger in QEMU


def _banner_gone(run=subprocess.run) -> tuple[bool, str]:
    """(test notification gone?, Shell.Eval output) for one read."""
    result = run(
        ["gdbus", "call", "--session",
         "--dest", "org.gnome.Shell",
         "--object-path", "/org/gnome/Shell",
         "--method", "org.gnome.Shell.Eval",
         BANNER_GONE_JS],
        capture_output=True, text=True, timeout=5,
    )
    out = result.stdout
    flat = out.replace("\\", "").replace('"', "").replace(" ", "")
    return "gone:true" in flat, out


@step("Notification banner is no longer showing via Shell.Eval")
def notification_banner_no_longer_showing(context, run=subprocess.run, pause=sleep) -> None:
    last_out = ""
    for _ in range(BANNER_DISMISS_TIMEOUT_S * 2):
        gone, last_out = _banner_gone(run)
        if gone:
            return
        pause(0.5)
    raise AssertionError(
        f"'{TEST_NOTIFICATION_TITLE}' is still shown or queued "
        f"{BANNER_DISMISS_TIMEOUT_S}s after CloseNotification; Shell.Eval returned: {last_out!r}"
    )


@step("No gnome-shell notification journal errors are present")
def no_gnome_shell_notification_journal_errors(context) -> None:
    output, returncode, stderr = _run_host("journalctl --no-pager -b -p err..emerg --lines=200")
    assert returncode == 0, f"journalctl failed: {stderr or output}"

    pattern = re.compile(r"gnome-shell.*notif", re.IGNORECASE)
    matches = [line for line in output.splitlines() if pattern.search(line)]
    assert not matches, f"Unexpected gnome-shell notification journal errors: {matches}"
