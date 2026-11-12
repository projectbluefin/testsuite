"""Real GNOME OS input/accessibility probe, executed only in a disposable guest.

The entry process never receives the random expected value. Only Ponytail's
virtual keyboard sends it; only the AT-SPI text interface reads it back.
"""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import time

TITLE = "GNOME OS input canary"
ENTRY_NAME = "Virtual keyboard target"
RESULTS = Path("/tmp/gnome_e2e/results")


def require_gnomeos_wayland(os_release, environ):
    identity = dict(line.split("=", 1) for line in shlex.split(os_release, comments=True))
    assert identity.get("ID") == "org.gnome.os", "Canary requires GNOME OS, never a substitute image"
    assert identity.get("GNOMEOS_COMMIT") and identity.get("IMAGE_VERSION"), "Missing GNOME OS build identity"
    assert environ.get("XDG_SESSION_TYPE") == "wayland", "Not a Wayland session"
    assert environ.get("WAYLAND_DISPLAY"), "Missing Wayland display"
    for name in ("DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS"):
        assert environ.get(name, "").startswith("unix:"), f"Missing {name}"
    assert environ["DBUS_SESSION_BUS_ADDRESS"] != environ["AT_SPI_BUS_ADDRESS"], "AT-SPI bus must be queried, not the session-bus fallback"
    return identity


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout.strip()


def entry_window():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    window = Gtk.Window(title=TITLE)
    entry = Gtk.Entry()
    entry.get_accessible().set_name(ENTRY_NAME)
    window.add(entry)
    window.set_default_size(480, 120)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    entry.grab_focus()
    window.present()
    Gtk.main()


def window_wait_diagnostics(child, run=subprocess.run):
    """What the shell reported when Ponytail never found the canary window."""
    def call(*args):
        try:
            done = run(args, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            return f"error: {error}"
        return (done.stdout or done.stderr).strip()[:2000]
    return {
        "entry_child_returncode": child.poll(),
        "introspect_windows": call(
            "gdbus", "call", "--session", "--dest", "org.gnome.Shell.Introspect",
            "--object-path", "/org/gnome/Shell/Introspect",
            "--method", "org.gnome.Shell.Introspect.GetWindows"),
        "shell_cmdline": call("pgrep", "-a", "-u", str(os.getuid()), "gnome-shell"),
        # Read-only: whether the Activities overview covers the desktop.
        "overview_visible": call(
            "gdbus", "call", "--session", "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell", "--method", "org.gnome.Shell.Eval",
            "Main.overview.visible"),
        "screenshot": call(
            "gdbus", "call", "--session", "--dest", "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot", "--method",
            "org.gnome.Shell.Screenshot.Screenshot", "false", "false",
            str(RESULTS / "window-wait.png")),
    }


def canary_window(ponytail):
    """The canary window as the shell lists it, or None while it isn't mapped."""
    for window in ponytail.window_list:
        if window.get("title") == TITLE:
            return window
    return None


def wait_for_window(ponytail, timeout=20, delay=0.5):
    """Wait until the shell lists the canary window. Focus is not required.

    Ponytail's own waitFor() only accepts a focused window, and on Wayland
    the shell doesn't give focus to a window a background process maps
    without an activation token, so it timed out with the window on screen.
    """
    deadline = time.monotonic() + timeout
    while True:
        window = canary_window(ponytail)
        if window is not None:
            return window
        if time.monotonic() >= deadline:
            raise ValueError("Timeout waiting for Window")
        time.sleep(delay)


XK_ESCAPE = 0xFF1B
PONYTAIL_SIGNAL_TIMEOUT = 15


def _glib():
    from gi.repository import GLib
    return GLib


def _signal_call(ponytail, invoke, signal, timeout=PONYTAIL_SIGNAL_TIMEOUT):
    """Call a Ponytail controller method and wait, bounded, for its signal.

    Ponytail's connectWindow/connectMonitor/disconnect wait on a GLib main
    loop with no timeout. When the daemon never sent the signal, the probe
    hung until the step's 90 s limit with no evidence of which call stuck.
    """
    glib = _glib()
    loop = glib.MainLoop()
    state = {"seen": False, "expired": False}

    def seen(*_):
        state["seen"] = True
        loop.quit()

    def expired():
        state["expired"] = True
        loop.quit()
        return False

    iface = ponytail.event_controller_iface
    ponytail.bus.add_signal_receiver(seen, signal, iface)
    tag = glib.timeout_add_seconds(timeout, expired)
    try:
        invoke(ponytail.event_controller, iface)
        if not state["seen"]:
            loop.run()
    finally:
        if not state["expired"]:
            glib.source_remove(tag)
        ponytail.bus.remove_signal_receiver(seen, signal, iface)
    if not state["seen"]:
        raise AssertionError(f"Ponytail never sent {signal} within {timeout}s")


def connect_window(ponytail, window_id):
    _signal_call(ponytail, lambda ctl, iface: ctl.ConnectWindow(window_id, dbus_interface=iface),
                 "Connected")
    ponytail.connected = window_id


def connect_monitor(ponytail, monitor=""):
    _signal_call(ponytail, lambda ctl, iface: ctl.ConnectMonitor(monitor, dbus_interface=iface),
                 "Connected")
    ponytail.connected = monitor


def disconnect(ponytail):
    _signal_call(ponytail, lambda ctl, iface: ctl.Disconnect(dbus_interface=iface), "Disconnected")
    ponytail.connected = None


def input_method_state(run=subprocess.run):
    """Whether an input method sits between the virtual keyboard and GTK."""
    def call(*args):
        try:
            done = run(args, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            return f"error: {error}"
        return (done.stdout or done.stderr).strip()[:500]
    return {
        "GTK_IM_MODULE": os.environ.get("GTK_IM_MODULE"),
        "ibus_daemon": call("pgrep", "-a", "-u", str(os.getuid()), "ibus-daemon"),
        "input_sources": call("gsettings", "get", "org.gnome.desktop.input-sources", "sources"),
    }


def _ponytail_debug(enabled):
    """Turn on the Ponytail daemon's g_debug log for the probe (journal only)."""
    verb = "set-environment" if enabled else "unset-environment"
    arg = "G_MESSAGES_DEBUG=all" if enabled else "G_MESSAGES_DEBUG"
    try:
        command("systemctl", "--user", verb, arg)
    except (OSError, subprocess.SubprocessError):
        pass


def _focused(ponytail):
    current = canary_window(ponytail)
    return current is not None and bool(current.get("has-focus"))


def focus_by_click(ponytail, window, timeout=10, delay=0.5):
    """Give the connected window keyboard focus with real virtual input.

    A GNOME session starts in the Activities overview, which covers a newly
    mapped window, so press Escape first to leave it (as a user would). If
    that isn't enough, click low in the window, inside the entry and clear
    of any title bar. Waits for the shell to report focus after each step and
    returns how focus arrived.
    """
    if window.get("has-focus"):
        return "already"
    ponytail.generateKeysymEvent(XK_ESCAPE)
    time.sleep(delay * 2)
    if _focused(ponytail):
        return "escape"
    x, y = int(window["width"]) // 2, max(1, int(window["height"]) - 30)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ponytail.generateButtonEvent(1, x, y)
        time.sleep(delay)
        if _focused(ponytail):
            return "click"
    raise AssertionError("Canary window never took keyboard focus after a virtual click")


def probe():
    identity = require_gnomeos_wayland(Path("/usr/lib/os-release").read_text(), os.environ)
    from dogtail import tree
    from ponytail.ponytail import Ponytail
    expected = secrets.token_hex(8)
    RESULTS.mkdir(parents=True, exist_ok=True)
    evidence = {"os_release": identity, "expected": expected, "observed": "",
                "shell": command("gnome-shell", "--version"), "gjs": command("gjs", "--version"),
                "mutter_build_version": Path("/opt/gnomeos-harness/mutter-version.txt").read_text().strip(),
                "session_type": os.environ["XDG_SESSION_TYPE"],
                "session_bus": os.environ["DBUS_SESSION_BUS_ADDRESS"],
                "atspi_bus": os.environ["AT_SPI_BUS_ADDRESS"]}
    assert evidence["shell"] and evidence["gjs"] and evidence["mutter_build_version"], "Unknown desktop versions"
    child = subprocess.Popen([sys.executable, __file__, "--entry"],
                             env={**os.environ, "GDK_BACKEND": "wayland", "NO_AT_BRIDGE": "0"})
    ponytail = None
    evidence["stage"] = "start"
    try:
        # Ponytail is D-Bus activated, so its daemon starts with this debug
        # log on and the guest journal shows what happens to each event.
        _ponytail_debug(True)
        try:
            ponytail = Ponytail()
        finally:
            _ponytail_debug(False)
        try:
            evidence["stage"] = "window-wait"
            window = wait_for_window(ponytail)
            # getWindowId (focus not required) returns the D-Bus id type
            # ConnectWindow expects, the same value waitFor() would return.
            evidence["stage"] = "connect-window"
            connect_window(ponytail, ponytail.getWindowId(TITLE))
            evidence["stage"] = "focus"
            evidence["focus"] = focus_by_click(ponytail, window)
        except (ValueError, AssertionError):
            # Say what the shell could see, so a timeout explains itself.
            evidence["window_wait"] = window_wait_diagnostics(child)
            print("gnomeos-canary window wait: " + json.dumps(evidence["window_wait"]),
                  file=sys.stderr, flush=True)
            raise
        # Type through a monitor connection, as dogtail does for keyboard input
        # (ponytail_helper.ponytail_check_connection): keys sent through a
        # window-scoped connection never reached the focused entry. ASCII
        # keysyms are their Unicode values. No AT-SPI text setter, shell eval,
        # clipboard or application command is allowed to supply the text.
        evidence["stage"] = "disconnect-window"
        disconnect(ponytail)
        evidence["stage"] = "connect-monitor"
        connect_monitor(ponytail)
        evidence["stage"] = "typing"
        for char in expected:
            ponytail.generateKeysymEvent(ord(char))
        evidence["input"] = "keysym-monitor"
        evidence["entry_found"] = False
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            matches = tree.root.findChildren(lambda node: node.name == ENTRY_NAME)
            if matches:
                evidence["entry_found"] = True
                evidence["observed"] = matches[0].text
                if evidence["observed"] == expected:
                    break
            time.sleep(0.25)
        if evidence["observed"] != expected:
            # Separate "the text never arrived" from "AT-SPI never found the
            # entry", and keep a picture of what the window showed.
            evidence["focused_after_typing"] = _focused(ponytail)
            evidence["after_typing_screenshot"] = window_wait_diagnostics(child)["screenshot"]
            evidence["input_method"] = input_method_state()
            print("gnomeos-canary readback: " + json.dumps(
                {k: evidence.get(k) for k in ("entry_found", "observed", "focused_after_typing",
                                              "focus", "input_method")}),
                file=sys.stderr, flush=True)
        evidence["stage"] = "readback"
        assert evidence["observed"] == expected, f"Virtual input was not observed over AT-SPI: {evidence}"
        screenshot = RESULTS / "desktop-canary.png"
        screenshot.unlink(missing_ok=True)
        command("gdbus", "call", "--session", "--dest", "org.gnome.Shell.Screenshot",
                "--object-path", "/org/gnome/Shell/Screenshot", "--method",
                "org.gnome.Shell.Screenshot.Screenshot", "false", "false", str(screenshot))
        assert screenshot.is_file() and screenshot.stat().st_size, "No fresh desktop screenshot"
        evidence["stage"] = "passed"
    except AssertionError as error:
        if str(error).startswith("Ponytail never sent"):
            print(f"gnomeos-canary stuck at {evidence['stage']}: {error}", file=sys.stderr, flush=True)
        raise
    finally:
        (RESULTS / "desktop-canary.json").write_text(json.dumps(evidence, indent=2) + "\n")
        child.terminate()
        child.wait(timeout=5)
        if ponytail is not None and ponytail.connected is not None:
            try:
                disconnect(ponytail)
            except AssertionError:
                pass  # already failing; don't hide the first error


if __name__ == "__main__":
    if sys.argv[1:] == ["--entry"]:
        entry_window()
    else:
        probe()
