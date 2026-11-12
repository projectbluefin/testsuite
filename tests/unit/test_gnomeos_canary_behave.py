"""The GNOME OS canary must hand behave the live session, not qecore's env.

qecore-headless rebuilds its environment from the first gnome-session
process and drops WAYLAND_DISPLAY and the session bus, so the canary's first
step failed with "Missing Wayland display" (#1144). The wrapper re-reads the
session after qecore's restart; these tests pin how it does that.
"""
from pathlib import Path

from scripts.gnomeos_canary_behave import (
    atspi_address, manager_environment, session_environment, wayland_socket,
)

ACTION = Path(__file__).parents[2] / ".github" / "actions" / "gnome-e2e" / "action.yml"
ATSPI = "unix:path=/run/user/1001/at-spi/bus_0,guid=0d4c6d8eb1a3c1a2"


def fake_run(manager="", atspi=""):
    def run(cmd, env):
        if cmd[:2] == ["systemctl", "--user"]:
            return manager
        if cmd[0] == "gdbus":
            return atspi
        return ""
    return run


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_manager_environment_parses_show_environment():
    out = "HOME=/home/x\nWAYLAND_DISPLAY=wayland-0\nDISPLAY=:0\nLANG='C.UTF-8'\n"
    env = manager_environment({}, fake_run(manager=out))
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["DISPLAY"] == ":0"
    assert env["LANG"] == "C.UTF-8"


def test_atspi_address_reads_gdbus_tuple():
    assert atspi_address({}, fake_run(atspi=f"('{ATSPI}',)\n")) == ATSPI
    assert atspi_address({}, fake_run(atspi="")) == ""
    assert atspi_address({}, fake_run(atspi="garbage")) == ""


def test_wayland_socket_skips_lock_files():
    assert wayland_socket("/run/user/1001", lambda _: ["bus", "wayland-0.lock", "wayland-0"]) == "wayland-0"
    assert wayland_socket("/run/user/1001", lambda _: ["bus"]) == ""


def test_session_environment_sets_every_variable_the_canary_asserts():
    clock = Clock()
    env = session_environment(
        1001, {"PATH": "/usr/bin"},
        run=fake_run(manager="WAYLAND_DISPLAY=wayland-0\n", atspi=f"('{ATSPI}',)"),
        listdir=lambda _: [], sleep=clock.sleep, clock=clock)
    # tests/shared/gnomeos_canary.py asserts exactly these.
    assert env["XDG_SESSION_TYPE"] == "wayland"
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1001/bus"
    assert env["AT_SPI_BUS_ADDRESS"] == ATSPI
    assert env["AT_SPI_BUS_ADDRESS"] != env["DBUS_SESSION_BUS_ADDRESS"]
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1001"
    assert env["PATH"] == "/usr/bin"


def test_session_environment_falls_back_to_the_socket_and_waits():
    calls = {"n": 0}

    def run(cmd, env):
        calls["n"] += 1
        if cmd[0] == "gdbus" and calls["n"] > 4:
            return f"('{ATSPI}',)"
        return ""

    clock = Clock()
    env = session_environment(1001, {}, run=run, listdir=lambda _: ["wayland-0"],
                              sleep=clock.sleep, clock=clock)
    assert env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["AT_SPI_BUS_ADDRESS"] == ATSPI
    assert clock.now > 0  # it waited for the bus instead of giving up


def test_session_environment_gives_up_at_the_deadline():
    clock = Clock()
    env = session_environment(1001, {}, run=fake_run(), listdir=lambda _: [],
                              sleep=clock.sleep, clock=clock, deadline_s=10)
    assert "WAYLAND_DISPLAY" not in env
    assert "AT_SPI_BUS_ADDRESS" not in env
    assert 10 <= clock.now <= 12


def test_action_runs_behave_through_the_wrapper_only_for_the_canary():
    text = ACTION.read_text(encoding="utf-8")
    step = text.partition("- name: Run behave via qecore-headless")[2].partition("\n    - name:")[0]
    canary = step.partition('if [[ "${GNOME_E2E_SUITE}" == "gnomeos-canary" ]]; then')[2].partition("\n        fi")[0]
    assert "gnomeos_canary_behave.py" in canary
    assert 'BEHAVE_PREFIX="/opt/gnomeos-harness/bin/python3 /tmp/gnome_e2e/gnomeos_canary_behave.py "' in canary
    assert 'BEHAVE_PREFIX=""' in step.partition("if [[")[0]
    assert '\\"${BEHAVE_PREFIX}\\$BEHAVE_BIN ' in step


def test_window_wait_diagnostics_reports_shell_view_and_child_state():
    from tests.shared.gnomeos_canary import window_wait_diagnostics

    class Child:
        def poll(self):
            return None  # still running

    class Done:
        def __init__(self, out):
            self.stdout, self.stderr = out, ""

    seen = []

    def run(args, **kwargs):
        seen.append(args[0])
        return Done("({uint64 1: {'title': <'GNOME OS desktop canary'>}},)" if args[0] == "gdbus" else "123 gnome-shell --unsafe-mode")

    report = window_wait_diagnostics(Child(), run=run)
    assert report["entry_child_returncode"] is None
    assert "GNOME OS desktop canary" in report["introspect_windows"]
    assert "--unsafe-mode" in report["shell_cmdline"]
    assert seen == ["gdbus", "pgrep"]


def test_window_wait_diagnostics_survives_failing_tools():
    from tests.shared.gnomeos_canary import window_wait_diagnostics

    class Child:
        def poll(self):
            return 1

    def run(args, **kwargs):
        raise FileNotFoundError(args[0])

    report = window_wait_diagnostics(Child(), run=run)
    assert report["entry_child_returncode"] == 1
    assert report["introspect_windows"].startswith("error:")
