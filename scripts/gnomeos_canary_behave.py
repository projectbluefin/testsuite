#!/usr/bin/env python3
"""Run behave inside the live GNOME OS canary session, then exec it.

qecore-headless replaces its environment with the first gnome-session
process's environ plus a short allowlist, then runs the user script with
`bash -c`. That environ has no WAYLAND_DISPLAY and no usable session bus, so
the canary's first step failed with "Missing Wayland display" (#1144). This
wrapper is the script qecore runs: it reads the session values after qecore's
GDM restart, exports them, and execs behave with its original arguments.

Usage: gnomeos_canary_behave.py BEHAVE_BIN [behave args...]
Standard library only; it runs on the guest's system Python.
"""
import ast
import json
import os
import subprocess
import sys
import time

DEADLINE_S = 60
POLL_S = 2


def _run(cmd, env):
    """Return stdout of cmd, or "" if it fails or is missing."""
    try:
        done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def manager_environment(env, run=_run):
    """The systemd user manager's environment as a dict (simple values only)."""
    values = {}
    for line in run(["systemctl", "--user", "show-environment"], env).splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            values[key] = value.strip("'\"")
    return values


def wayland_socket(runtime_dir, listdir=os.listdir):
    """First wayland-N socket in the runtime dir, ignoring lock files."""
    try:
        names = sorted(listdir(runtime_dir))
    except OSError:
        return ""
    for name in names:
        if name.startswith("wayland-") and not name.endswith(".lock"):
            return name
    return ""


def atspi_address(env, run=_run):
    """The accessibility bus address, as org.a11y.Bus reports it."""
    out = run(["gdbus", "call", "--session", "--dest", "org.a11y.Bus",
               "--object-path", "/org/a11y/bus", "--method", "org.a11y.Bus.GetAddress"], env)
    try:
        (address,) = ast.literal_eval(out.strip())
    except (ValueError, SyntaxError, TypeError):
        return ""
    return address if isinstance(address, str) else ""


def session_environment(uid, base_env, run=_run, listdir=os.listdir,
                        sleep=time.sleep, clock=time.monotonic, deadline_s=DEADLINE_S):
    """Session variables for behave, waiting until the restarted shell is up."""
    runtime = f"/run/user/{uid}"
    env = dict(base_env)
    env["XDG_RUNTIME_DIR"] = runtime
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
    env["XDG_SESSION_TYPE"] = "wayland"
    end = clock() + deadline_s
    while True:
        manager = manager_environment(env, run)
        display = manager.get("WAYLAND_DISPLAY") or wayland_socket(runtime, listdir)
        address = atspi_address(env, run)
        if (display and address) or clock() >= end:
            break
        sleep(POLL_S)
    if display:
        env["WAYLAND_DISPLAY"] = display
    if manager.get("DISPLAY"):
        env["DISPLAY"] = manager["DISPLAY"]
    if address:
        env["AT_SPI_BUS_ADDRESS"] = address
    return env


def main(argv):
    if len(argv) < 2:
        print("usage: gnomeos_canary_behave.py BEHAVE_BIN [args...]", file=sys.stderr)
        return 2
    env = session_environment(os.getuid(), os.environ)
    names = ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS")
    print("gnomeos-canary session env: " + json.dumps({n: env.get(n, "") for n in names}),
          file=sys.stderr, flush=True)
    # Exec even when a value is missing: the canary's own first step then
    # reports exactly which one, instead of this wrapper failing opaquely.
    os.execvpe(argv[1], argv[1:], env)
    return 1  # not reached


if __name__ == "__main__":
    sys.exit(main(sys.argv))
