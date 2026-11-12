#!/usr/bin/env python3
"""Enable screenshot access at Shell startup in the disposable canary image.

The canary restarts gnome-shell with --unsafe-mode. qecore-headless builds
behave's environment from /proc/<gnome-session pid>/environ, not the SSH shell,
and the --unsafe-mode GDM restart replaces the session, so the values the action
sourced into the SSH shell (/tmp/gnome_e2e_session.env) go stale. Writing the
session environment to ~/.config/environment.d/ lets the restarted shell carry
WAYLAND_DISPLAY, DBUS_SESSION_BUS_ADDRESS, XDG_RUNTIME_DIR and AT_SPI_BUS_ADDRESS
to behave, the same way e2e.yml keeps PATH alive across the restart.
"""
from pathlib import Path
import shlex

# Stable across a GDM restart: the runtime dir and the D-Bus / AT-SPI sockets are
# recreated at these fixed paths, so pinning them is safe. WAYLAND_DISPLAY is set
# to the first display the action sources (wayland-0 in the canary).
CANARY_SESSION_ENV = (
    "XDG_RUNTIME_DIR=/run/user/1001\n"
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus\n"
    "AT_SPI_BUS_ADDRESS=unix:path=/run/user/1001/at-spi\n"
    "WAYLAND_DISPLAY=wayland-0\n"
    "XDG_SESSION_TYPE=wayland\n"
)
USER_HOME = Path("var/home/bluefin-test")


def write_canary_session_env(root=Path("/")):
    """Persist the session environment so the restarted shell carries it to behave."""
    dropin = root / USER_HOME / ".config/environment.d/99-canary-session.conf"
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text(CANARY_SESSION_ENV)
    print(f"Canary session env: {dropin}")


def configure(root=Path("/")):
    write_canary_session_env(root)
    units = root / "usr/lib/systemd/user"
    services = [units / name for name in (
        "org.gnome.Shell@wayland.service", "org.gnome.Shell@.service",
    ) if (units / name).is_file()]
    if not services:
        raise ValueError("No supported GNOME Shell user service in pinned image")
    for service in services:
        commands = [line.removeprefix("ExecStart=") for line in service.read_text().splitlines()
                    if line.startswith("ExecStart=")]
        if len(commands) != 1:
            raise ValueError(f"Expected one ExecStart in {service}")
        command = commands[0]
        executable = shlex.split(command)[0]
        if executable != "/usr/bin/gnome-shell" or not (root / executable.lstrip("/")).is_file():
            raise ValueError(f"Unknown Shell executable in {service}: {command}")
        dropin = units / f"{service.name}.d/50-canary-unsafe-mode.conf"
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(f"[Service]\nExecStart=\nExecStart={command} --unsafe-mode\n")
        print(f"Canary Shell startup: {service.name}: {command} --unsafe-mode")


if __name__ == "__main__":
    configure()
