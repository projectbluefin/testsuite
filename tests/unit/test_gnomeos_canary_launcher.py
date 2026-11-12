import json
import os
from pathlib import Path
import subprocess
import sys


LAUNCHER = Path(__file__).resolve().parents[2] / "scripts/run_gnomeos_canary_behave.sh"


def test_launcher_passes_live_session_to_child(tmp_path):
    for name, output in {
        "systemctl": "WAYLAND_DISPLAY=wayland-7\n",
        "gdbus": "('unix:path=/run/user/42/at-spi/bus,guid=abc',)\n",
    }.items():
        command = tmp_path / name
        command.write_text(f"#!/bin/sh\nprintf '%s' \"{output}\"\n")
        command.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin"}
    child = "import json,os; print(json.dumps(dict(os.environ)))"
    result = subprocess.run(
        ["bash", str(LAUNCHER), sys.executable, "-c", child],
        env=env, capture_output=True, text=True, check=True,
    )
    actual = json.loads(result.stdout)
    runtime = f"/run/user/{os.getuid()}"
    assert actual["XDG_RUNTIME_DIR"] == runtime
    assert actual["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime}/bus"
    assert actual["WAYLAND_DISPLAY"] == "wayland-7"
    assert actual["XDG_SESSION_TYPE"] == "wayland"
    assert actual["AT_SPI_BUS_ADDRESS"] == "unix:path=/run/user/42/at-spi/bus,guid=abc"
