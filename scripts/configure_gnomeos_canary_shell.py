#!/usr/bin/env python3
"""Enable screenshot access at Shell startup in the disposable canary image."""
from pathlib import Path
import shlex


def configure(root=Path("/")):
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
