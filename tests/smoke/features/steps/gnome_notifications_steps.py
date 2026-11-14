"""Custom step definitions for GNOME notification smoke tests."""
import json
import os
import re
import subprocess
import uuid
from time import sleep

from behave import step
from tests.shared.ssh_config import ssh_argv

# Summary prefix of the notifications the smoke scenarios send. Each send adds
# a unique suffix: scenarios that send without closing (and retries) leave
# same-titled notifications in the tray, so a bare title cannot say whether
# this scenario's notification was dismissed.
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
    title = f"{TEST_NOTIFICATION_TITLE} {uuid.uuid4().hex[:8]}"
    context.test_notification_title = title
    output, returncode, stderr = _run(
        "gdbus call --session "
        "--dest org.freedesktop.Notifications "
        "--object-path /org/freedesktop/Notifications "
        "--method org.freedesktop.Notifications.Notify "
        f"'' 0 '' '{title}' 'Testsuite notification body' '[]' '{{}}' 3000"
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
def dismiss_notification_via_gdbus(context, run=subprocess.run, pause=sleep) -> None:
    notification_id = getattr(context, "notification_id", None)
    assert notification_id is not None, (
        "No notification ID captured — run 'A test desktop notification is sent via gdbus' first"
    )
    # The dismissal check can only prove CloseNotification removed the
    # notification if Shell was seen holding it first; otherwise a tray API
    # change (or a notification that never arrived) would read as "gone".
    title = _sent_title(context)
    state = {}
    for _ in range(NOTIFICATION_SEEN_TIMEOUT_S * 2):
        state = _tray_state(title, run)
        if not state.get("error") and (state.get("queued") or state.get("shown")):
            break
        pause(0.5)
    else:
        raise AssertionError(
            f"'{title}' was never seen in the message tray or as the banner within "
            f"{NOTIFICATION_SEEN_TIMEOUT_S}s of sending, so its dismissal cannot be "
            f"checked; last tray state: {state}"
        )
    context.test_notification_seen = True
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
def banner_gone_js(title: str) -> str:
    """Shell.Eval JS: where is the notification titled ``title``?

    Returns a JSON object: ``shown`` (it is the visible banner), ``queued`` (it
    is in the message tray) and ``error`` (the tray could not be read). An
    error is never reported as gone.
    """
    return (
        "(() => { const title = " + json.dumps(title) + ";"
        " let shown = false, queued = false, error = null, banner = null, idle = null;"
        " try { const t = Main.messageTray; const b = t._banner;"
        "  shown = !!(b && b.visible && b.notification && b.notification.title === title);"
        "  banner = b ? ((b.notification && b.notification.title) || '?') : null;"
        "  queued = t.getSources().some(s => s.notifications.some(n => n.title === title)); }"
        " catch (e) { error = String(e); }"
        " try { idle = global.backend.get_core_idle_monitor().get_idletime(); } catch (e) {}"
        " return JSON.stringify({ shown: shown, queued: queued, error: error,"
        "  banner: banner, idle_ms: idle }); })()"
    )


BANNER_DISMISS_TIMEOUT_S = 20  # GNOME 50 banners can linger in QEMU
NOTIFICATION_SEEN_TIMEOUT_S = 5


def _parse_eval_json(out: str):
    """The object a JSON-returning Shell.Eval call produced, or None.

    Shell.Eval answers ``(true, '"<JSON string>"')``: a GVariant string holding
    the JSON encoding of the string the expression returned.
    """
    m = re.match(r"\(\s*(true|false)\s*,\s*'(.*)'\s*\)\s*$", out.strip(), re.S)
    if not m or m.group(1) != "true":
        return None
    literal = m.group(2).replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")
    try:
        value = json.loads(literal)
        return json.loads(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _tray_state(title: str, run=subprocess.run) -> dict:
    """Shell's view of the notification titled ``title``; ``error`` set on any failure."""
    try:
        result = run(
            ["gdbus", "call", "--session",
             "--dest", "org.gnome.Shell",
             "--object-path", "/org/gnome/Shell",
             "--method", "org.gnome.Shell.Eval",
             banner_gone_js(title)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"gdbus failed: {exc}"}
    state = _parse_eval_json(result.stdout)
    if not isinstance(state, dict):
        return {"error": f"unusable Shell.Eval reply: {result.stdout!r}"}
    return state


def _sent_title(context) -> str:
    title = getattr(context, "test_notification_title", None)
    assert title, (
        "No test notification was sent in this scenario — run 'A test desktop "
        "notification is sent via gdbus' first"
    )
    return title


def _banner_gone(title: str, run=subprocess.run) -> tuple[bool, dict]:
    """(test notification gone?, tray state) for one read; an error is not gone."""
    state = _tray_state(title, run)
    gone = not state.get("error") and not state.get("shown") and not state.get("queued")
    return gone, state


@step("Notification banner is no longer showing via Shell.Eval")
def notification_banner_no_longer_showing(context, run=subprocess.run, pause=sleep) -> None:
    title = _sent_title(context)
    assert getattr(context, "test_notification_seen", False), (
        f"'{title}' was not seen before CloseNotification, so its dismissal cannot be "
        "checked — run 'Dismiss the notification via gdbus CloseNotification' first"
    )
    state = {}
    for _ in range(BANNER_DISMISS_TIMEOUT_S * 2):
        gone, state = _banner_gone(title, run)
        if gone:
            return
        pause(0.5)
    raise AssertionError(
        f"'{title}' is still shown or queued, or the tray could not be read, "
        f"{BANNER_DISMISS_TIMEOUT_S}s after CloseNotification; last tray state: {state}"
    )


@step("No gnome-shell notification journal errors are present")
def no_gnome_shell_notification_journal_errors(context) -> None:
    output, returncode, stderr = _run_host("journalctl --no-pager -b -p err..emerg --lines=200")
    assert returncode == 0, f"journalctl failed: {stderr or output}"

    pattern = re.compile(r"gnome-shell.*notif", re.IGNORECASE)
    matches = [line for line in output.splitlines() if pattern.search(line)]
    assert not matches, f"Unexpected gnome-shell notification journal errors: {matches}"
