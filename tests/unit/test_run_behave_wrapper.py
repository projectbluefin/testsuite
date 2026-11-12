"""The canary wrapper must read the live desktop env, not stale SSH values.

qecore-headless (4.19.3) rebuilds behave's environment from the running GNOME
session and keeps only PYTHONPATH/TEST/TERM/GNOME_ACCESSIBILITY/QECORE_*, so the
SSH-sourced display/bus/AT-SPI values go stale after the --unsafe-mode GDM
restart. This wrapper runs after that restart and pins its shape: it must read
the live values and exec behave, and qecore requires the first word of the
command to be an executable, so the action passes /bin/bash to run it.
"""

from pathlib import Path

WRAPPER = Path(__file__).resolve().parent.parent.parent / "scripts" / "run-behave.sh"


def test_wrapper_reads_live_values_and_execs_behave():
    src = WRAPPER.read_text()

    # Runtime dir + session bus come from the live uid, not a pinned path.
    assert "uid=$(id -u)" in src
    assert "XDG_RUNTIME_DIR=/run/user/$uid" in src
    assert "DBUS_SESSION_BUS_ADDRESS=" in src

    # WAYLAND_DISPLAY is read back from the live user manager (matches whatever
    # session qecore started), and the AT-SPI address is re-read at run time
    # (it carries a fresh guid after the GDM restart).
    assert "systemctl --user show-environment" in src
    assert "WAYLAND_DISPLAY" in src
    assert "org.a11y.Bus GetAddress" in src

    # The first word of the command is an executable (/bin/bash), and behave
    # runs the canary suite's features with the CI result writers.
    assert src.strip().splitlines()[0] == "#!/bin/bash"
    assert "exec" in src
    assert "gnomeos-canary/features/" in src
    assert "--format json.pretty" in src
