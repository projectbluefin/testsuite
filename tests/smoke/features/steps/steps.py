"""
Custom step definitions for GNOME Shell smoke tests.

common_steps provides: Application is running, Item found/not found,
Left/Right click, Key combo, Press key, Type text, Run and save command output,
Last command output, Wait N seconds.

Custom steps here cover:
- GNOME Shell accessibility check (retrying via context.sandbox.shell)
- Activities overview state, search bar content.

NOTE: We do NOT redefine 'Application "{name}" is running' — behave raises
AmbiguousStep when a literal step conflicts with an existing wildcard step.
Instead we use a distinct step name: 'GNOME Shell is accessible via AT-SPI'.

Step patterns sourced from: modehnal/GNOMETerminalAutomation steps.py
dogtail API: root.application(), Node.findChild(), Node.child(roleName=)
"""
import os
import subprocess
import time
from time import sleep

from behave import step

try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass
from tests.shared.gnome_shell_steps import *  # noqa: F401,F403
from tests.shared.ssh_config import ssh_argv

# Same container detection as system_health_steps — /proc/1/ns/mnt is a symlink
# to a kernel namespace object so lexists() is required (isfile() returns False).
_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")


def _run_host(cmd: str, timeout: int = 30):
    """Run cmd on the host VM via SSH when inside the runner container."""
    if _IN_CONTAINER:
        result = subprocess.run(
            ssh_argv() + [cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        # qecore-headless replaces os.environ with gnome-session's /proc/<pid>/environ.
        # On dbus-broker sessions DBUS_SESSION_BUS_ADDRESS may be absent; the well-known
        # socket at /run/user/<uid>/bus is always present for active sessions.
        env = dict(os.environ)
        if not env.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        if not os.path.exists("/tmp/session.env"):
            try:
                with open("/tmp/session.env", "w") as f:
                    for k in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DISPLAY", "XDG_SESSION_TYPE"):
                        v = env.get(k)
                        if v:
                            f.write(f"export {k}={v}\n")
            except Exception:  # noqa: BLE001
                pass
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


# ── D-Bus helpers (GNOME 50: Shell.Eval requires unsafe_mode, which cannot be
# enabled from a cold session via D-Bus. Use stable org.gnome.Shell properties
# and methods instead.) ──

def _gdbus_call(
    method: str,
    interface: str = "org.gnome.Shell",
    object_path: str = "/org/gnome/Shell",
    args: str = "",
) -> str:
    """Call a D-Bus method on org.gnome.Shell via gdbus (routed over SSH in CI)."""
    cmd = (
        "source /tmp/session.env 2>/dev/null; "
        f"gdbus call --session --dest org.gnome.Shell "
        f"--object-path {object_path} "
        f"--method {interface}.{method} {args}"
    ).strip()
    stdout, rc, stderr = _run_host(cmd)
    assert rc == 0, f"gdbus {interface}.{method} failed: {stderr}"
    return stdout.strip()


def _gdbus_property_get(interface: str, property_name: str) -> str:
    """Get a D-Bus property on org.gnome.Shell."""
    return _gdbus_call(
        method="org.freedesktop.DBus.Properties.Get",
        args=f"{interface} {property_name}",
    )


def _gdbus_property_set(interface: str, property_name: str, value: str) -> None:
    """Set a D-Bus property on org.gnome.Shell; value is a GVariant string."""
    _gdbus_call(
        method="org.freedesktop.DBus.Properties.Set",
        args=f"{interface} {property_name} {value}",
    )


# ── Shell.Eval helpers (GNOME 50: uinput Super + AT-SPI toggle click broken) ──

def _shell_eval(js: str) -> str:
    """Run JS in GNOME Shell via gdbus and return raw stdout.

    Always re-enables unsafe_mode before evaluation — GNOME 50 resets it
    after UI interactions (modal dialogs, overview open/close, etc.).
    Returns the raw gdbus output string, e.g. ``(true, 'some value')\\n``.
    Use _eval_bool() when you need to check a JS boolean result.

    Routes via SSH when running inside the runner container — the container
    cannot connect to the VM's systemd user session bus directly.
    """
    import shlex
    # Prepend unsafe_mode enable — GNOME 50 resets it after UI events.
    js = f'global.context.unsafe_mode = true; {js}'
    cmd = (
        "source /tmp/session.env 2>/dev/null; "
        "gdbus call --session "
        "--dest org.gnome.Shell "
        "--object-path /org/gnome/Shell "
        "--method org.gnome.Shell.Eval "
        + shlex.quote(js)
    )
    stdout, rc, stderr = _run_host(cmd)
    assert rc == 0, f"Shell.Eval({js!r}) failed (rc={rc}): {stderr}"
    print(f"Shell.Eval({js!r}) → {stdout}", flush=True)
    return stdout


def _eval_bool(js: str) -> bool:
    """Evaluate a JS expression that returns true/false via Shell.Eval.

    Parses the gdbus return format ``(true, 'true')`` / ``(true, 'false')``.
    GNOME 50 may wrap the JS result in extra double quotes: ``(true, '"true"')``.
    Extracts only the **second** tuple element (the JS result string).
    Raises AssertionError if the result cannot be parsed as a boolean.
    """
    import re
    out = _shell_eval(js)
    # gdbus format: (success_bool, 'js_result_string')
    # GNOME 50 may return (true, '"true"') with extra double-quotes around the result.
    # We must match the JS result (after the comma), not the success flag.
    m = re.search(r',\s*\'"?(true|false)"?\'\s*\)', out, re.IGNORECASE)
    if m:
        return m.group(1).lower() == 'true'
    raise AssertionError(
        f"Shell.Eval did not return a boolean for {js!r}: got {out!r}"
    )


def _wait_eval_bool(js: str, expected: bool, retries: int = 8, delay: float = 0.5) -> bool:
    """Poll _eval_bool(js) until it equals expected, or return False on timeout."""
    for _ in range(retries):
        try:
            if _eval_bool(js) == expected:
                return True
        except AssertionError:
            pass
        sleep(delay)
    return False


def _gsettings_set_bool(schema: str, key: str, value: bool) -> None:
    val = "true" if value else "false"
    stdout, rc, stderr = _run_host(
        f"source /tmp/session.env 2>/dev/null; gsettings set {schema} {key} {val}"
    )
    assert rc == 0, (
        f"gsettings set {schema} {key} failed: rc={rc}\n{stderr}"
    )


def _gsettings_get_bool(schema: str, key: str) -> bool:
    stdout, rc, stderr = _run_host(
        f"source /tmp/session.env 2>/dev/null; gsettings get {schema} {key}"
    )
    assert rc == 0, (
        f"gsettings get {schema} {key} failed: rc={rc}\n{stderr}"
    )
    value = stdout.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise AssertionError(f"Unexpected gsettings value for {schema} {key}: {stdout!r}")


_DND_TOGGLE_JS = (
    "(() => { "
    "const quickSettings = Main.panel.statusArea.quickSettings; "
    "return quickSettings._doNotDisturb || "
    "quickSettings._do_not_disturb || "
    "quickSettings._dnd || null; "
    "})()"
)


def _overview_active() -> bool:
    """Read the org.gnome.Shell OverviewActive property via busctl.

    busctl is used instead of gdbus because gdbus requires GVariant angle
    brackets (<true>) which are misinterpreted as shell redirection operators
    by the SSH/wrapper layer that prefixes commands with ``source /tmp/session.env``.
    """
    cmd = (
        "source /tmp/session.env 2>/dev/null; "
        "busctl --user get-property org.gnome.Shell /org/gnome/Shell org.gnome.Shell OverviewActive"
    )
    stdout, rc, stderr = _run_host(cmd)
    assert rc == 0, f"busctl get-property OverviewActive failed: {stderr}"
    return stdout.strip().endswith("true")


def _set_overview_active(active: bool) -> None:
    """Set the org.gnome.Shell OverviewActive property via busctl."""
    value = "true" if active else "false"
    cmd = (
        "source /tmp/session.env 2>/dev/null; "
        f"busctl --user set-property org.gnome.Shell /org/gnome/Shell org.gnome.Shell OverviewActive b {value}"
    )
    stdout, rc, stderr = _run_host(cmd)
    assert rc == 0, f"busctl set-property OverviewActive {value} failed: {stderr}"


def _wait_overview_active(expected: bool, retries: int = 12, delay: float = 0.5) -> bool:
    """Poll OverviewActive until it equals expected or timeout."""
    for _ in range(retries):
        try:
            if _overview_active() == expected:
                return True
        except AssertionError:
            pass
        sleep(delay)
    return False


def _overview_search_entry(context, timeout: int = 10):
    """Find the overview search entry in the gnome-shell AT-SPI tree.

    GNOME 50 headless QEMU: the search entry role varies (text/entry) and its
    accessible name may be the placeholder "Type to search…" or empty.  Search
    the whole gnome-shell tree and prefer a search-like name.
    """
    shell = context.sandbox.shell
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = shell.findChildren(
            lambda n: n.showing and n.roleName in {"text", "entry"}
        )
        for candidate in candidates:
            name = (candidate.name or "").lower()
            if "search" in name or "type to" in name:
                return candidate
        if candidates:
            return candidates[0]
        sleep(0.2)
    raise AssertionError("Overview search entry not found in AT-SPI tree")


def _dismiss_welcome_dialog(attempts: int = 10, delay: float = 0.5) -> bool:
    """Dismiss the Bluefin first-boot Welcome dialog if it blocks the session.

    Fresh CI VMs show a "Welcome to Bluefin" modal with Skip/Take Tour buttons.
    Click Skip so subsequent AT-SPI steps can reach the overview search entry.
    """
    try:
        from dogtail import tree
    except Exception:  # noqa: BLE001
        return False
    for _ in range(attempts):
        skip_buttons = tree.root.findChildren(
            lambda n: n.showing
            and n.roleName in {"push button", "button"}
            and (n.name or "").strip().lower() == "skip"
        )
        if not skip_buttons:
            sleep(delay)
            continue
        try:
            skip_buttons[0].click()
        except Exception:  # noqa: BLE001
            try:
                actions = skip_buttons[0].actions or {}
                for action in ("click", "press", "activate"):
                    if action in actions:
                        skip_buttons[0].do_action_named(action)
                        break
            except Exception:  # noqa: BLE001
                pass
        return True
    return False


@step('Dismiss the Bluefin welcome dialog if it appears')
def dismiss_welcome_dialog(context) -> None:
    """Behave step wrapper for _dismiss_welcome_dialog."""
    _dismiss_welcome_dialog()


def _node_text_value(node) -> str:
    """Return the accessible text of a node, including child text entries.

    GNOME 50's overview search entry sometimes stores the typed text on a child
    text node rather than on the entry itself; gather text from all children too.
    """
    parts = []
    name = (getattr(node, "name", "") or "").strip()
    if name:
        parts.append(name)
    try:
        text = (getattr(node, "text", "") or "").strip()
        if text:
            parts.append(text)
    except Exception:  # noqa: BLE001
        pass
    for child in getattr(node, "children", []) or []:
        child_text = _node_text_value(child)
        if child_text and child_text not in parts:
            parts.append(child_text)
    return " ".join(parts)


def _loginctl_session_id() -> str:
    """Return the first graphical session ID from loginctl."""
    stdout, rc, _ = _run_host(
        "loginctl list-sessions --no-legend 2>/dev/null | "
        "awk '$4 ~ /seat/ || $5 == \"user\" {print $1; exit}'"
    )
    if not stdout.strip():
        stdout, rc, _ = _run_host("loginctl list-sessions --no-legend 2>/dev/null | head -1")
    assert rc == 0, f"loginctl list-sessions failed: {stdout}"
    assert stdout.strip(), "No loginctl sessions found"
    return stdout.strip().split()[0]


def _session_locked_hint() -> bool:
    """Return the logind LockedHint for the current session."""
    session_id = _loginctl_session_id()
    stdout, rc, _ = _run_host(
        f"loginctl show-session {session_id} --property=LockedHint 2>/dev/null"
    )
    assert rc == 0, f"loginctl show-session {session_id} failed: {stdout}"
    return "LockedHint=yes" in stdout


def _dnd_toggle_exists_js() -> str:
    # GNOME 50: _doNotDisturb may exist as an object but lack a .checked property.
    # Verify both the toggle and its .checked accessor exist before relying on it.
    return f"({_DND_TOGGLE_JS})?.checked !== undefined"


def _dnd_toggle_checked_js() -> str:
    return f"({_DND_TOGGLE_JS}).checked.toString()"


def _dnd_toggle_toggle_js() -> str:
    return f"({_DND_TOGGLE_JS}).toggle()"


def _set_dnd_enabled(expected: bool) -> None:
    # In GNOME 48+, the _do_not_disturb property on quickSettings may not exist
    # or may have been relocated.  Try the Shell.Eval UI path first; if the
    # toggle object is absent, fall back to the gsettings canonical source.
    # (DND is active when org.gnome.desktop.notifications show-banners = false)
    try:
        toggle_exists = _eval_bool(_dnd_toggle_exists_js())
    except AssertionError:
        toggle_exists = False

    if toggle_exists:
        checked_js = _dnd_toggle_checked_js()
        toggle_js = _dnd_toggle_toggle_js()
        if _eval_bool(checked_js) != expected:
            _shell_eval(toggle_js)
        if not _wait_eval_bool(checked_js, expected=expected, retries=8, delay=0.5):
            out = _shell_eval(checked_js)
            raise AssertionError(
                f"Do-Not-Disturb did not reach {expected} — Shell.Eval returned: {out!r}"
            )
    else:
        # Fallback: drive DND through gsettings
        # show-banners=true → DND disabled; show-banners=false → DND enabled
        _gsettings_set_bool(
            "org.gnome.desktop.notifications", "show-banners", not expected
        )
        actual = _gsettings_get_bool("org.gnome.desktop.notifications", "show-banners")
        dnd_active = not actual
        if dnd_active != expected:
            raise AssertionError(
                f"Do-Not-Disturb gsettings fallback: expected DND={expected}, "
                f"show-banners={actual!r}"
            )


# Distinct phrase from tests/shared/ssh_steps.py's local-coredump step — this
# one checks the host VM over SSH (via _run_host). Sharing the phrase raises
# AmbiguousStep because ssh_steps is star-imported by offline_boot_steps.
@step('No coredump entries exist on the host for "{name}"')
def no_coredump_entries_exist(context, name: str) -> None:
    stdout, returncode, stderr = _run_host(
        f"coredumpctl list {name} --no-pager --lines=10 2>&1 || true"
    )
    # coredumpctl exits 0 when matches found, 1 when no matches — treat 2+ as error
    if "command not found" in stdout or "command not found" in stderr:
        print(f"coredumpctl not available: {stdout or stderr}", flush=True)
        return
    matches = [line for line in stdout.splitlines() if name in line]
    assert not matches, f"Unexpected coredump entries for {name}: {matches}"


@step('No journal entries at priority "{priority}" contain "{text}"')
def no_journal_entries_at_priority_contain(context, priority: str, text: str) -> None:
    stdout, returncode, stderr = _run_host(
        f"journalctl --no-pager -b -p {priority} --lines=50"
    )
    assert returncode == 0, (
        f"journalctl failed for priority {priority}: rc={returncode}\n"
        f"stdout: {stdout}\n"
        f"stderr: {stderr}"
    )
    matches = [line for line in stdout.splitlines() if text in line]
    assert not matches, f"Unexpected journal matches for {text!r}: {matches}"


@step('Open Activities overview')
def open_activities_overview(context) -> None:
    """Open the Activities overview via the stable org.gnome.Shell D-Bus property."""
    _set_overview_active(True)
    sleep(0.2)


@step('Close Activities overview via D-Bus')
def close_activities_overview_via_dbus(context) -> None:
    """Close the Activities overview via the stable org.gnome.Shell D-Bus property."""
    _set_overview_active(False)
    sleep(0.2)


@step('Quick Settings panel is open via Shell.Eval')
def quick_settings_open_eval(context) -> None:
    if not _wait_eval_bool(
        'Main.panel.statusArea.quickSettings.menu.isOpen.toString()',
        expected=True, retries=6, delay=0.5,
    ):
        out = _shell_eval('Main.panel.statusArea.quickSettings.menu.isOpen.toString()')
        raise AssertionError(f"Quick Settings not open — Shell.Eval returned: {out!r}")


@step('Ensure Night Light starts disabled via gsettings')
def ensure_night_light_starts_disabled(context) -> None:
    _gsettings_set_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
        False,
    )
    assert not _gsettings_get_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
    ), 'Night Light should start disabled'


@step('Enable Night Light via gsettings')
def enable_night_light_via_gsettings(context) -> None:
    _gsettings_set_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
        True,
    )


@step('Night Light is enabled via gsettings')
def night_light_is_enabled_via_gsettings(context) -> None:
    assert _gsettings_get_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
    ), 'Night Light should be enabled'


@step('Disable Night Light via gsettings')
def disable_night_light_via_gsettings(context) -> None:
    _gsettings_set_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
        False,
    )


@step('Night Light is disabled via gsettings')
def night_light_is_disabled_via_gsettings(context) -> None:
    assert not _gsettings_get_bool(
        'org.gnome.settings-daemon.plugins.color',
        'night-light-enabled',
    ), 'Night Light should be disabled'


@step('Enable Do-Not-Disturb via Shell.Eval toggle')
def enable_do_not_disturb_via_shell_eval_toggle(context) -> None:
    _set_dnd_enabled(True)


@step('Do-Not-Disturb is enabled via Shell.Eval')
def do_not_disturb_is_enabled_via_shell_eval(context) -> None:
    # Prefer Shell.Eval UI check; fall back to gsettings if toggle not available.
    checked_js = _dnd_toggle_checked_js()
    try:
        ok = _wait_eval_bool(checked_js, expected=True, retries=8, delay=0.5)
    except AssertionError:
        ok = False
    if not ok:
        # gsettings fallback: show-banners=false means DND is enabled
        dnd_active = not _gsettings_get_bool(
            'org.gnome.desktop.notifications', 'show-banners'
        )
        assert dnd_active, 'Do-Not-Disturb should be enabled'


@step('Disable Do-Not-Disturb via Shell.Eval toggle')
def disable_do_not_disturb_via_shell_eval_toggle(context) -> None:
    _set_dnd_enabled(False)


@step('Do-Not-Disturb is disabled via Shell.Eval')
def do_not_disturb_is_disabled_via_shell_eval(context) -> None:
    # Prefer Shell.Eval UI check; fall back to gsettings if toggle not available.
    checked_js = _dnd_toggle_checked_js()
    try:
        ok = _wait_eval_bool(checked_js, expected=False, retries=8, delay=0.5)
    except AssertionError:
        ok = False
    if not ok:
        # gsettings fallback: show-banners=true means DND is disabled
        dnd_active = not _gsettings_get_bool(
            'org.gnome.desktop.notifications', 'show-banners'
        )
        assert not dnd_active, 'Do-Not-Disturb should be disabled'


@step('Date menu panel is open via Shell.Eval')
def date_menu_open_eval(context) -> None:
    if not _wait_eval_bool(
        'Main.panel.statusArea.dateMenu.menu.isOpen.toString()',
        expected=True, retries=6, delay=0.5,
    ):
        out = _shell_eval('Main.panel.statusArea.dateMenu.menu.isOpen.toString()')
        raise AssertionError(f"Date menu not open — Shell.Eval returned: {out!r}")


@step('Type "{text}" in overview search entry')
def type_in_overview_search_entry(context, text: str) -> None:
    """Type text into the overview search entry via dogtail/rawinput.

    GNOME 50 headless: opening the overview via D-Bus shows it but may not give
    keyboard focus to the search entry.  Click the entry first, then type.
    """
    entry = _overview_search_entry(context)
    try:
        entry.click()
    except Exception:  # noqa: BLE001
        try:
            entry.grabFocus()
        except Exception:  # noqa: BLE001
            pass
    sleep(0.2)
    from dogtail.rawinput import typeText

    typeText(text)
    sleep(0.2)


@step("Lock screen via loginctl")
def lock_screen_via_loginctl(context) -> None:
    """Lock the GNOME session via loginctl lock-session (robust in headless)."""
    session_id = _loginctl_session_id()
    stdout, rc, stderr = _run_host(f"loginctl lock-session {session_id}")
    assert rc == 0, f"loginctl lock-session failed: {stderr}\n{stdout}"
    sleep(0.5)


@step("Session is locked")
def session_is_locked(context) -> None:
    """Assert the current session is in a locked state via logind LockedHint."""
    for _ in range(20):
        if _session_locked_hint():
            return
        sleep(0.5)
    raise AssertionError("Session is not locked after 10s")


@step("Unlock screen via loginctl")
def unlock_screen_via_loginctl(context) -> None:
    """Unlock the GNOME session via loginctl unlock-session (robust in headless)."""
    session_id = _loginctl_session_id()
    stdout, rc, stderr = _run_host(f"loginctl unlock-session {session_id}")
    assert rc == 0, f"loginctl unlock-session failed: {stderr}\n{stdout}"

    for _ in range(20):
        if not _session_locked_hint():
            return
        sleep(0.5)

    raise AssertionError("Session is still locked after unlock attempt")


@step("Active workspace index is noted")
def note_active_workspace_index(context) -> None:
    """Store the current workspace index for later comparison."""
    import re
    out = _shell_eval(
        "global.workspace_manager.get_active_workspace_index();"
    )
    m = re.search(r',\s*\'"?(\d+)"?\'\s*\)', out)
    try:
        context.initial_workspace_index = int(m.group(1)) if m else 0
    except (ValueError, AttributeError):
        context.initial_workspace_index = 0
    print(f"Initial workspace index: {context.initial_workspace_index}", flush=True)


@step("Switch to next workspace via Shell.Eval")
def switch_to_next_workspace_via_shell_eval(context) -> None:
    """Switch to the next workspace using workspace_manager."""
    _shell_eval(
        "global.workspace_manager.get_active_workspace().get_neighbor("
        "Meta.MotionDirection.RIGHT).activate(global.get_current_time());"
    )
    sleep(0.5)


@step("Active workspace has changed")
def active_workspace_has_changed(context) -> None:
    """Assert the active workspace index changed from the noted value."""
    import re
    initial = getattr(context, 'initial_workspace_index', 0)
    for _ in range(10):
        out = _shell_eval(
            "global.workspace_manager.get_active_workspace_index();"
        )
        m = re.search(r',\s*\'"?(\d+)"?\'\s*\)', out)
        try:
            current = int(m.group(1)) if m else None
        except (ValueError, AttributeError):
            sleep(0.5)
            continue
        if current is not None and current != initial:
            return
        sleep(0.5)
    raise AssertionError(
        f"Workspace index did not change from {initial}"
    )


@step("Overview is open")
def overview_is_open(context) -> None:
    """Check the org.gnome.Shell OverviewActive D-Bus property.

    GNOME 50 headless QEMU reports Main.overview.visible=false even when the
    overview is shown; the D-Bus property tracks the same state but is exposed
    without requiring Shell.Eval/unsafe_mode.
    """
    if not _wait_overview_active(expected=True, retries=12):
        raise AssertionError("Activities overview did not open after 6s")


@step("Overview is closed")
def overview_is_closed(context) -> None:
    """Check the org.gnome.Shell OverviewActive D-Bus property."""
    if not _wait_overview_active(expected=False, retries=12):
        raise AssertionError("Activities overview is still showing after 6s")


@step('Overview search bar contains "{text}"')
def overview_search_bar_contains(context, text: str) -> None:
    """Verify the overview search entry text via AT-SPI.

    GNOME 50 disables Shell.Eval outside unsafe mode, and unsafe mode cannot be
    enabled from a cold session via D-Bus, so we read the accessible text of the
    search entry directly.
    """
    for _ in range(20):
        entry = _overview_search_entry(context)
        current = _node_text_value(entry)
        if text in current:
            print(f"Overview search bar text: {current!r}", flush=True)
            return
        sleep(0.2)
    raise AssertionError(
        f"Overview search bar does not contain {text!r}"
    )


@step("Wayland session type is active")
def wayland_session_active(context) -> None:
    stdout, returncode, stderr = _run_host(
        "source /tmp/session.env 2>/dev/null; "
        "printf '%s\\n' \"${XDG_SESSION_TYPE:-}\"; "
        "if [ -z \"${XDG_SESSION_TYPE:-}\" ]; then "
        "session_id=$(loginctl list-sessions --no-legend 2>/dev/null | awk 'NR==1{print $1}'); "
        "[ -n \"$session_id\" ] && loginctl show-session \"$session_id\" --property=Type --value 2>/dev/null || true; "
        "fi"
    )
    assert returncode == 0, f"Unable to determine session type: {stderr or stdout}"
    values = [line.strip().lower() for line in stdout.splitlines() if line.strip()]
    assert "wayland" in values, f"Session type is not Wayland: {stdout.strip()!r}"


@step("GNOME Shell is not using software rendering")
def no_llvmpipe(context) -> None:
    stdout, returncode, stderr = _run_host(
        "source /tmp/session.env 2>/dev/null; "
        "{ glxinfo -B 2>/dev/null | grep 'OpenGL renderer string' || "
        "journalctl -b _COMM=gnome-shell --no-pager -n 200 2>/dev/null | "
        "grep -i llvmpipe | head -1 || "
        "echo 'no_llvmpipe'; }"
    )
    assert returncode == 0, f"Renderer check failed: {stderr or stdout}"
    lower = stdout.lower()
    assert "llvmpipe" not in lower or "no_llvmpipe" in lower, (
        f"LLVMpipe (software rendering) detected: {stdout.strip()!r}"
    )


@step("Dash to Dock panel is visible")
def dash_to_dock_visible(context) -> None:
    # First distinguish an extension activation failure from a rendering
    # failure through GNOME Shell's public Extensions D-Bus API.
    # GNOME 50 exposes Extensions interface on /org/gnome/Shell (fallback to /org/gnome/Shell/Extensions)
    output = None
    for obj_path in ("/org/gnome/Shell", "/org/gnome/Shell/Extensions"):
        try:
            output = _gdbus_call(
                method="GetExtensionInfo",
                interface="org.gnome.Shell.Extensions",
                object_path=obj_path,
                args="'dash-to-dock@micxgx.gmail.com'",
            )
            break
        except AssertionError:
            continue
    assert output is not None, "Failed to query Dash to Dock extension info via D-Bus"
    import re

    match = re.search(r"'state':\s*<(?:[a-zA-Z0-9_]+\s+)?(\d+)(?:\.0)?>", output)
    assert match, f"Dash to Dock extension info lacked a state: {output!r}"
    assert match.group(1) == "1", (
        "Dash to Dock is not enabled according to org.gnome.Shell.Extensions: "
        f"state={match.group(1)}"
    )
    # Dash-to-Dock v106 names its rendered top-level actor
    # "dashtodockContainer". Traverse the public Clutter actor tree rather
    # than the extension's private stateObj/dockManager object graph, then
    # require a mapped, opaque, allocated dock whose slide container is open.
    visible = _wait_eval_bool(
        "(() => { "
        "const findDock = actor => { "
        "if (actor.get_name?.() === 'dashtodockContainer') return actor; "
        "for (const child of actor.get_children?.() ?? []) { "
        "const found = findDock(child); if (found) return found; "
        "} return null; }; "
        "const dock = findDock(global.stage); "
        "if (!dock || !dock.is_mapped() || !dock.is_visible() || dock.opacity === 0) return false; "
        "const slider = dock.get_child(); "
        "if (!slider || slider.slideX < 0.9) return false; "
        "const [width, height] = dock.get_transformed_size(); "
        "return width > 1 && height > 1; "
        "})().toString()",
        expected=True,
        retries=10,
        delay=0.2,
    )
    assert visible, "Dash to Dock extension is enabled but its panel is not visibly rendered"


@step("System tray area is present in the panel")
def system_tray_present(context) -> None:
    present = _eval_bool(
        "(() => { "
        "try { "
        "const panel = Main.panel; "
        "const rightBox = panel._rightBox; "
        "if (!rightBox) return false; "
        "const quickSettings = panel.statusArea.quickSettings; "
        "return rightBox.visible === true && quickSettings !== null && quickSettings !== undefined; "
        "} catch (e) { return false; } "
        "})().toString()"
    )
    assert present, "System tray area is not present in GNOME Shell panel"

DOCUMENT_VIEWERS = {"org.gnome.Papers.desktop", "evince.desktop", "okular.desktop"}
IMAGE_VIEWERS = {"org.gnome.Loupe.desktop", "eog.desktop", "gthumb.desktop", "shotwell.desktop"}
TEXT_EDITORS = {"org.gnome.TextEditor.desktop", "gedit.desktop", "gnome-text-editor.desktop"}
VIDEO_PLAYERS = {"org.gnome.Showtime.desktop", "io.github.celluloid_player.Celluloid.desktop", "totem.desktop", "vlc.desktop", "mpv.desktop"}


def _xdg_mime_default(mime_type: str) -> str:
    # When running inside the runner container, xdg-mime is not available on the
    # host — the MIME database lives in the QEMU VM.  Route via SSH in that case.
    # XDG_DATA_DIRS must include Flatpak export paths so Flatpak-installed app
    # MIME registrations (Firefox, Papers, Loupe, Showtime) are visible to
    # xdg-mime query; SSH sessions don't inherit the user session XDG_DATA_DIRS.
    from app_support import _IN_CONTAINER, _ssh_run
    if _IN_CONTAINER:
        result = _ssh_run(
            "XDG_DATA_DIRS=/var/lib/flatpak/exports/share"
            ":/home/bluefin-test/.local/share/flatpak/exports/share"
            ":/usr/local/share:/usr/share "
            f"xdg-mime query default {mime_type}"
        )
        return result.stdout.strip()
    result = subprocess.run(
        ["xdg-mime", "query", "default", mime_type],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@step('xdg-mime query default for "{mime_type}" returns "{desktop_file}"')
def xdg_mime_exact(context, mime_type: str, desktop_file: str) -> None:
    actual = _xdg_mime_default(mime_type)
    assert actual == desktop_file, (
        f"MIME type {mime_type!r}: expected {desktop_file!r}, got {actual!r}"
    )


@step('xdg-mime query default for "{mime_type}" returns a document viewer')
def xdg_mime_doc_viewer(context, mime_type: str) -> None:
    actual = _xdg_mime_default(mime_type)
    assert actual in DOCUMENT_VIEWERS, (
        f"MIME type {mime_type!r}: {actual!r} is not a known document viewer. "
        f"Expected one of {DOCUMENT_VIEWERS}"
    )


@step('xdg-mime query default for "{mime_type}" returns an image viewer')
def xdg_mime_image_viewer(context, mime_type: str) -> None:
    actual = _xdg_mime_default(mime_type)
    assert actual in IMAGE_VIEWERS, (
        f"MIME type {mime_type!r}: {actual!r} is not a known image viewer. "
        f"Expected one of {IMAGE_VIEWERS}"
    )


@step('xdg-mime query default for "{mime_type}" returns a text editor')
def xdg_mime_text_editor(context, mime_type: str) -> None:
    actual = _xdg_mime_default(mime_type)
    assert actual in TEXT_EDITORS, (
        f"MIME type {mime_type!r}: {actual!r} is not a known text editor. "
        f"Expected one of {TEXT_EDITORS}"
    )


@step('xdg-mime query default for "{mime_type}" returns a video player')
def xdg_mime_video_player(context, mime_type: str) -> None:
    actual = _xdg_mime_default(mime_type)
    assert actual in VIDEO_PLAYERS, (
        f"MIME type {mime_type!r}: {actual!r} is not a known video player. "
        f"Expected one of {VIDEO_PLAYERS}"
    )


@step('Flatpak "{app_id}" is installed system-wide')
def flatpak_installed_system_wide(context, app_id: str) -> None:
    """Assert app_id is present in the system Flatpak installation on the VM."""
    stdout, rc, stderr = _run_host(f"flatpak info --system {app_id}")
    assert rc == 0, f"{app_id} not installed system-wide: {stderr or stdout}"


@step('Flatpak "{app_id}" sandbox does not have excessive filesystem permissions')
def flatpak_no_excessive_permissions(context, app_id: str) -> None:
    """Assert app_id is installed and its sandbox lacks host/home filesystem access."""
    stdout, rc, stderr = _run_host(f"flatpak info --system {app_id}")
    assert rc == 0, f"{app_id} not installed system-wide — cannot audit permissions: {stderr or stdout}"
    perms_out, perms_rc, _ = _run_host(
        f"flatpak info --system --show-permissions {app_id}"
    )
    import re
    assert not re.search(r"filesystems=(host|home)", perms_out), (
        f"{app_id} has excessive filesystem access:\n{perms_out}"
    )


# ── Compass launcher (org.tunaos.compass Flatpak, Super+Space) ──

_COMPASS_VISIBLE_JS = (
    "global.get_window_actors().some(a => { const w = a.meta_window; "
    "const ids = [w.get_wm_class(), w.get_wm_class_instance(), "
    "w.get_gtk_application_id(), w.get_sandboxed_app_id(), w.get_title()]"
    ".join(' ').toLowerCase(); "
    "return ids.includes('compass') && a.visible && !w.minimized "
    "&& w.showing_on_its_workspace(); })"
)
_WINDOWS_JS = (
    "JSON.stringify(global.get_window_actors().map(a => { const w = a.meta_window; "
    "return [w.get_wm_class(), w.get_gtk_application_id(), "
    "w.get_sandboxed_app_id(), w.get_title(), a.visible, w.minimized]; }))"
)


@step("Compass Flatpak is installed system-wide within {timeout:d} seconds")
def compass_flatpak_installed_within(context, timeout: int) -> None:
    # flatpak-preinstall downloads a ~71 MB extra-data AppImage at boot.
    # The VM e2e lane masks flatpak-preinstall.service (no first-boot network
    # pulls), so Compass can never appear there: skip instead of timing out.
    state, _, _ = _run_host("systemctl is-enabled flatpak-preinstall.service")
    if state == "masked":
        context.scenario.skip("flatpak-preinstall.service is masked in this lane")
        return
    deadline = time.monotonic() + timeout
    while True:
        out, rc, err = _run_host("flatpak info --system org.tunaos.compass")
        if rc == 0:
            return
        assert time.monotonic() < deadline, (
            f"org.tunaos.compass not installed after {timeout}s: {err or out}"
        )
        sleep(10)


_SESSION = "source /tmp/session.env 2>/dev/null; "


@step("Compass user service is wanted by graphical-session.target")
def compass_service_wanted_by_session(context) -> None:
    enabled, _, _ = _run_host(_SESSION + "systemctl --user is-enabled compass.service")
    exec_start, _, _ = _run_host(_SESSION + "systemctl --user show -p ExecStart compass.service")
    print(f"compass.service is-enabled={enabled!r} {exec_start}", flush=True)
    wanted_by, rc, err = _run_host(_SESSION + "systemctl --user show -p WantedBy compass.service")
    assert rc == 0 and "graphical-session.target" in wanted_by, (
        f"compass.service not wanted by graphical-session.target: {wanted_by!r} {err}"
    )


@step("Compass user service is restarted and answers ping within {timeout:d} seconds")
def compass_service_restarted_and_pings(context, timeout: int) -> None:
    # ConditionPathExists is false at login when preinstall finishes later.
    _, rc, err = _run_host(_SESSION + "systemctl --user restart compass.service")
    assert rc == 0, f"systemctl --user restart compass.service failed: {err}"
    deadline = time.monotonic() + timeout
    while True:
        active, _, _ = _run_host(_SESSION + "systemctl --user is-active compass.service")
        out, ping_rc, ping_err = _run_host(_SESSION + "flatpak run org.tunaos.compass ping")
        if active == "active" and ping_rc == 0:
            return
        if time.monotonic() >= deadline:
            status, _, _ = _run_host(
                _SESSION + "systemctl --user status --no-pager compass.service 2>&1"
            )
            raise AssertionError(
                f"compass.service not serving after {timeout}s: is-active={active!r} "
                f"ping rc={ping_rc} {ping_err or out}\n{status}"
            )
        sleep(2)



@step("Compass launcher window is {state} within {timeout:d} seconds")
def compass_window_state_within(context, state: str, timeout: int) -> None:
    assert state in ("visible", "hidden"), f"unknown state {state!r}"
    if _wait_eval_bool(_COMPASS_VISIBLE_JS, state == "visible", retries=timeout, delay=1):
        return
    raise AssertionError(
        f"Compass window not {state} after {timeout}s; windows: {_shell_eval(_WINDOWS_JS)}"
    )
