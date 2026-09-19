"""Custom step definitions for power-status-color extension AT-SPI and
state-transition tests.

Covers the ``power-status-color@projectbluefin.io`` GNOME Shell extension
from ``projectbluefin/bluefin-bling``: presence/enablement, reaction to the
``/run/reboot-required`` flag file (yellow alert, ``power-status-reboot``
style class), the uptime-overdue alert (red, ``power-status-overdue``,
precedence over the reboot alert), and lifecycle/teardown hygiene on
disable.

Style-class checks and simulated alert states go through ``Shell.Eval``
(GNOME Shell's ``org.gnome.Shell.Eval`` D-Bus method) since CSS style
classes on St actors are not exposed via AT-SPI. Simulating 30+ days of
uptime is done by stubbing the extension's own ``_checkUptimeOverdue``
probe and invoking its real ``_checkStatus`` precedence logic — the file
monitor / reboot-flag path is exercised for real via an actual file on the
host.
"""

import os
import re
import subprocess
import time
from time import sleep

from behave import step
from tests.shared.ssh_config import ssh_argv

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")

POWER_STATUS_UUID = "power-status-color@projectbluefin.io"
CLASS_OVERDUE = "power-status-overdue"
CLASS_REBOOT = "power-status-reboot"
REBOOT_FLAG_FILE = "/run/reboot-required"

# JS snippet locating the Quick Settings power button actor, mirroring
# PowerStatusColorExtension._findPowerButton() in bluefin-bling.
_POWER_BUTTON_JS = (
    "(() => {"
    "const qs = Main.panel?.statusArea?.quickSettings;"
    "return qs?._system?._systemItem?.menu?.sourceActor ?? null;"
    "})()"
)


def _run_host(cmd, timeout: int = 30):
    """Run cmd on the host VM via SSH when inside the runner container."""
    import shlex
    cmd_str = cmd if isinstance(cmd, str) else " ".join(shlex.quote(a) for a in cmd)
    if _IN_CONTAINER:
        result = subprocess.run(
            ssh_argv() + [cmd_str],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    else:
        _local_env = dict(os.environ)
        if not _local_env.get("DBUS_SESSION_BUS_ADDRESS"):
            _local_env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        if isinstance(cmd, list):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=_local_env)
        else:
            result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout, check=False, env=_local_env)
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _shell_eval(js: str, timeout: int = 5) -> str:
    """Run JS in GNOME Shell via gdbus and return raw stdout.

    Mirrors ``tests.shared.gnome_shell_steps._shell_eval`` — kept local so
    this module has no import-order dependency on shared step registration.
    """
    js = f"global.context.unsafe_mode = true; {js}"
    output, returncode, stderr = _run_host(
        [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell",
            "--method", "org.gnome.Shell.Eval",
            js,
        ],
        timeout=timeout,
    )
    assert returncode == 0, f"Shell.Eval failed: {stderr or output}"
    print(f"Shell.Eval({js!r}) -> {output}", flush=True)
    return output


def _eval_bool(js: str) -> bool:
    out = _shell_eval(js)
    match = re.search(r",\s*'\"?(true|false)\"?'\s*\)", out, re.IGNORECASE)
    if match:
        return match.group(1).lower() == "true"
    raise AssertionError(f"Could not parse boolean from Shell.Eval output: {out}")


def _has_style_class(class_name: str) -> bool:
    js = (
        f"(() => {{const btn = {_POWER_BUTTON_JS}; "
        f"return btn ? !!btn.has_style_class_name('{class_name}') : false;}})().toString()"
    )
    return _eval_bool(js)


def _wait_for_style_class(class_name: str, expected: bool, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if _has_style_class(class_name) == expected:
                return True
        except AssertionError:
            pass
        if time.monotonic() >= deadline:
            return False
        sleep(0.5)


def _extension_stub_js(body: str) -> str:
    """Wrap ``body`` with a lookup of the extension's live stateObj."""
    return (
        "(() => {"
        f"const ext = Main.extensionManager.lookup('{POWER_STATUS_UUID}')?.stateObj; "
        "if (!ext) return 'no-ext'; "
        f"{body} "
        "return 'ok';"
        "})()"
    )


@step('GNOME extension "{uuid}" is disabled')
def gnome_extension_is_disabled_step(context, uuid: str) -> None:
    output, returncode, stderr = _run_host(["gnome-extensions", "disable", uuid])
    assert returncode == 0, f"gnome-extensions disable {uuid} failed: {stderr or output}"
    sleep(1)


@step('GNOME extension "{uuid}" is re-enabled')
def gnome_extension_is_re_enabled_step(context, uuid: str) -> None:
    output, returncode, stderr = _run_host(["gnome-extensions", "enable", uuid])
    assert returncode == 0, f"gnome-extensions enable {uuid} failed: {stderr or output}"
    sleep(1)


def _run_admin(cmd: str, timeout: int = 30):
    """Run a command as root with non-interactive sudo; fall back once.

    Mirrors ``printing_steps._run_admin`` — the reboot-required flag file
    lives under ``/run``, which is root-owned on the target VM.
    """
    out, rc, err = "", 1, ""
    for prefix in ("sudo -n", ""):
        full = f"{prefix} {cmd}".strip() if prefix else cmd
        out, rc, err = _run_host(full, timeout=timeout)
        if rc == 0:
            return out, rc, err
        combined = (out + " " + err).lower()
        if "unauthorized" not in combined and "permission denied" not in combined:
            break
    return out, rc, err


@step('file "{path}" is created on the host')
def file_is_created_on_host(context, path: str) -> None:
    output, returncode, stderr = _run_admin(f"touch {path}")
    assert returncode == 0, f"Failed to create {path}: {stderr or output}"


@step('file "{path}" is removed from the host')
def file_is_removed_from_host(context, path: str) -> None:
    output, returncode, stderr = _run_admin(f"rm -f {path}")
    assert returncode == 0, f"Failed to remove {path}: {stderr or output}"


@step('Quick Settings power button has style class "{class_name}" within {seconds:d} seconds')
def power_button_has_style_class_within(context, class_name: str, seconds: int) -> None:
    assert _wait_for_style_class(class_name, True, seconds), (
        f"Power button did not gain style class {class_name!r} within {seconds}s"
    )


@step('Quick Settings power button does not have style class "{class_name}" within {seconds:d} seconds')
def power_button_lacks_style_class_within(context, class_name: str, seconds: int) -> None:
    assert _wait_for_style_class(class_name, False, seconds), (
        f"Power button still has style class {class_name!r} after {seconds}s"
    )


@step('Quick Settings power button has style class "{class_name}"')
def power_button_has_style_class(context, class_name: str) -> None:
    assert _has_style_class(class_name), f"Power button does not have style class {class_name!r}"


@step('Quick Settings power button does not have style class "{class_name}"')
def power_button_lacks_style_class(context, class_name: str) -> None:
    assert not _has_style_class(class_name), f"Power button unexpectedly has style class {class_name!r}"


@step("Quick Settings power button has no power status alert style classes")
def power_button_has_no_alert_classes(context) -> None:
    for class_name in (CLASS_OVERDUE, CLASS_REBOOT):
        assert not _has_style_class(class_name), (
            f"Power button unexpectedly retained style class {class_name!r}"
        )


@step("the power status color extension simulates uptime overdue and re-evaluates status")
def simulate_uptime_overdue(context) -> None:
    # Stub the extension's own uptime probe (real 30-day uptime is not
    # reproducible in CI) and drive the real _checkStatus() precedence
    # logic — the reboot-flag path above is exercised without any stub.
    out = _shell_eval(
        _extension_stub_js(
            "ext.__origCheckUptime = ext._checkUptimeOverdue; "
            "ext._checkUptimeOverdue = () => Promise.resolve(true); "
            "ext._checkStatus();"
        )
    )
    assert "no-ext" not in out, f"{POWER_STATUS_UUID} stateObj not found: {out}"
    assert _wait_for_style_class(CLASS_OVERDUE, True, 5), (
        "Power button did not gain the uptime-overdue style class after simulation"
    )


@step("the power status color extension stops simulating uptime overdue and re-evaluates status")
def stop_simulating_uptime_overdue(context) -> None:
    out = _shell_eval(
        _extension_stub_js(
            "if (ext.__origCheckUptime) {"
            "ext._checkUptimeOverdue = ext.__origCheckUptime; "
            "delete ext.__origCheckUptime;"
            "} "
            "ext._checkStatus();"
        )
    )
    assert "no-ext" not in out, f"{POWER_STATUS_UUID} stateObj not found: {out}"


@step("No power-status-color extension GJS or St warnings exist in the journal")
def no_power_status_color_journal_warnings(context) -> None:
    output, returncode, stderr = _run_host(
        ["journalctl", "--no-pager", "-b", "-p", "warning..emerg", "--lines=500", "-q"]
    )
    assert returncode == 0, f"journalctl failed: {stderr or output}"

    pattern = re.compile(r"power-status-color|PowerStatusColor", re.IGNORECASE)
    matches = [line for line in output.splitlines() if pattern.search(line)]
    assert not matches, (
        "Unexpected power-status-color journal warnings/errors found:\n"
        + "\n".join(matches)
    )


@step("the power status color extension has no active file monitor or timer")
def extension_has_no_active_monitor_or_timer(context) -> None:
    # After disable() the extension's stateObj is torn down entirely, so
    # extensionManager.lookup(...).stateObj is null/undefined — that absence
    # itself is the cleanest available evidence that no dangling monitor or
    # timer closures survive on a live instance.
    js = (
        "(() => {"
        f"const ext = Main.extensionManager.lookup('{POWER_STATUS_UUID}')?.stateObj; "
        "return (ext == null).toString();"
        "})()"
    )
    assert _eval_bool(js), (
        f"{POWER_STATUS_UUID} still has a live stateObj after disable(); "
        "expected teardown to release it (see extension.js disable())."
    )
