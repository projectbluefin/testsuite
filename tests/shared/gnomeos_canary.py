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
    try:
        ponytail = Ponytail()
        window_id = ponytail.waitFor(TITLE, timeout=20)
        ponytail.connectWindow(window_id)
        # ASCII keysyms are their Unicode values; no AT-SPI text setter, shell
        # eval, clipboard or application command is allowed to supply the text.
        for char in expected:
            ponytail.generateKeysymEvent(ord(char))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            matches = tree.root.findChildren(lambda node: node.name == ENTRY_NAME)
            if matches:
                evidence["observed"] = matches[0].text
                if evidence["observed"] == expected:
                    break
            time.sleep(0.25)
        assert evidence["observed"] == expected, f"Virtual input was not observed over AT-SPI: {evidence}"
        screenshot = RESULTS / "desktop-canary.png"
        screenshot.unlink(missing_ok=True)
        command("gdbus", "call", "--session", "--dest", "org.gnome.Shell.Screenshot",
                "--object-path", "/org/gnome/Shell/Screenshot", "--method",
                "org.gnome.Shell.Screenshot.Screenshot", "false", "false", str(screenshot))
        assert screenshot.is_file() and screenshot.stat().st_size, "No fresh desktop screenshot"
    finally:
        (RESULTS / "desktop-canary.json").write_text(json.dumps(evidence, indent=2) + "\n")
        child.terminate()
        child.wait(timeout=5)
        if ponytail is not None and ponytail.connected is not None:
            ponytail.disconnect()


if __name__ == "__main__":
    if sys.argv[1:] == ["--entry"]:
        entry_window()
    else:
        probe()
