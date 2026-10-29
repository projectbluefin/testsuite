"""Keep the GUI probe in a bounded child process; no fallback input paths."""
import ast
import os
import signal
from pathlib import Path
import subprocess
import sys

from behave import given, when, then

from tests.shared.gnomeos_canary import command, require_gnomeos_wayland


@given("the guest is a genuine GNOME OS Wayland desktop")
def genuine_guest(context):
    # qecore rebuilds the environment from the GNOME session after any GDM
    # restart. Query the live accessibility bus here rather than reusing an old
    # address or falling back to the session bus.
    address, = ast.literal_eval(command(
        "gdbus", "call", "--session", "--dest", "org.a11y.Bus",
        "--object-path", "/org/a11y/bus", "--method", "org.a11y.Bus.GetAddress",
    ))
    os.environ["AT_SPI_BUS_ADDRESS"] = address
    require_gnomeos_wayland(Path("/usr/lib/os-release").read_text(), os.environ)
    # Do not run untrusted extensions under the existing administrative harness.
    installed = subprocess.run(["gnome-extensions", "list"], check=True,
                               capture_output=True, text=True, timeout=15)
    assert not installed.stdout.strip(), "Baseline canary requires a guest without extensions"


@when("virtual input types into the canary window")
def input_canary(context):
    script = Path(__file__).resolve().parents[3] / "shared/gnomeos_canary.py"
    child = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
    try:
        assert child.wait(timeout=90) == 0, "GNOME OS input/accessibility probe failed"
    finally:
        # A blocked Ponytail connection must not leave its GTK child behind.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


@then("accessibility reports the exact text and desktop evidence is saved")
def canary_evidence(context):
    import json
    results = Path("/tmp/gnome_e2e/results")
    data = json.loads((results / "desktop-canary.json").read_text())
    assert data["expected"] == data["observed"] and data["observed"]
    assert (results / "desktop-canary.png").stat().st_size > 0
