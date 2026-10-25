import os
import shlex
import shutil
import subprocess

from tests.shared.ssh_config import ssh_argv


# When behave runs inside the runner container the host VM filesystem is not
# visible: /usr/share/applications, flatpak, etc. are absent from the image.
# Detect container context so desktop/flatpak lookups and app launches can be
# forwarded to the VM via SSH instead.
_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")

DESKTOP_DIRS = (
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
)

# Exported Flatpak desktop entries are ordinary-looking files whose launch
# environment does not cross into the Flatpak sandbox.
FLATPAK_EXPORT_MARKER = "/flatpak/exports/share/applications/"


def _ssh_args() -> list[str]:
    """Canonical SSH argv — see tests/shared/ssh_config.py."""
    return ssh_argv()


def _ssh_run(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        _ssh_args() + [cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def _desktop_path(desktop_id: str) -> str | None:
    if _IN_CONTAINER:
        for d in DESKTOP_DIRS:
            r = _ssh_run(f"test -f {d}/{desktop_id} && echo {d}/{desktop_id}")
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        return None
    for directory in DESKTOP_DIRS:
        path = os.path.join(directory, desktop_id)
        if os.path.exists(path):
            return path
    return None


def _flatpak_available(app_id: str) -> bool:
    if _IN_CONTAINER:
        return _ssh_run(f"flatpak info {app_id} 2>/dev/null").returncode == 0
    return subprocess.run(
        ["flatpak", "info", app_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _env_exports(env: dict[str, str] | None) -> str:
    """Render ``env`` as a shell ``export`` prefix for remote launches."""
    if not env:
        return ""
    return "".join(f"export {k}={shlex.quote(v)}; " for k, v in sorted(env.items()))


def _flatpak_env_args(env: dict[str, str] | None) -> list[str]:
    """Render ``env`` as ``flatpak run --env=`` arguments.

    Environment variables set outside the sandbox are not visible inside it, so
    they must be forwarded explicitly.
    """
    if not env:
        return []
    return [f"--env={k}={v}" for k, v in sorted(env.items())]


def _flatpak_desktop_app_id(desktop_path: str, desktop_id: str) -> str | None:
    """Return the Flatpak app ID when ``desktop_path`` is a Flatpak export."""
    if FLATPAK_EXPORT_MARKER not in desktop_path:
        return None
    if desktop_id.endswith(".desktop"):
        return desktop_id[: -len(".desktop")]
    return desktop_id


def _ssh_launch(cmd: str, env: dict[str, str] | None = None) -> None:
    """Launch an app on the VM via SSH; returns immediately (fire-and-forget)."""
    # Source session.env to get DBUS_SESSION_BUS_ADDRESS + WAYLAND_DISPLAY,
    # then run the launch command detached so SSH disconnect doesn't kill it.
    full = (
        "source /tmp/session.env 2>/dev/null; "
        f"{_env_exports(env)}nohup {cmd} </dev/null &>/dev/null & disown"
    )
    subprocess.run(_ssh_args() + [full], capture_output=True, text=True, timeout=15)


def _launch_flatpak(
    app_id: str,
    env: dict[str, str] | None,
    local_env: dict[str, str] | None,
) -> None:
    """Start a Flatpak while forwarding the application environment."""
    flatpak_args = ["flatpak", "run", *_flatpak_env_args(env), app_id]
    if _IN_CONTAINER:
        _ssh_launch(" ".join(shlex.quote(a) for a in flatpak_args), env)
    else:
        subprocess.Popen(
            flatpak_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=local_env,
        )


def launch_target_available(targets: tuple[tuple[str, str], ...]) -> bool:
    for kind, value in targets:
        if kind == "command":
            if _IN_CONTAINER:
                if _ssh_run(f"command -v {value}").returncode == 0:
                    return True
            elif shutil.which(value):
                return True
        if kind == "desktop" and _desktop_path(value):
            return True
        if kind == "flatpak" and _flatpak_available(value):
            return True
    return False


def launch_background(
    targets: tuple[tuple[str, str], ...],
    env: dict[str, str] | None = None,
) -> str:
    """Launch the first available target in the background.

    ``env`` is applied to the launched process only. It is exported before the
    command in SSH mode, merged into ``os.environ`` for local ``Popen`` calls,
    and forwarded across the Flatpak sandbox boundary with ``--env=``.
    Applications that gate their AT-SPI bridge on an environment variable (such
    as Firefox, which needs ``GNOME_ACCESSIBILITY=1``) must be launched this way
    or they never appear in the accessibility tree.
    """
    local_env = {**os.environ, **env} if env else None
    for kind, value in targets:
        if kind == "command":
            if _IN_CONTAINER:
                if _ssh_run(f"command -v {value}").returncode == 0:
                    _ssh_launch(value, env)
                    return f"command:{value}"
            elif shutil.which(value):
                subprocess.Popen(
                    [value],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=local_env,
                )
                return f"command:{value}"
        if kind == "desktop":
            dp = _desktop_path(value)
            if dp:
                app_id = _flatpak_desktop_app_id(dp, value)
                if app_id:
                    _launch_flatpak(app_id, env, local_env)
                    return f"flatpak:{app_id}"
                if _IN_CONTAINER:
                    _ssh_launch(f"gio launch {dp}", env)
                else:
                    subprocess.Popen(
                        ["gtk-launch", value],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=local_env,
                    )
                return f"desktop:{value}"
        if kind == "flatpak" and _flatpak_available(value):
            _launch_flatpak(value, env, local_env)
            return f"flatpak:{value}"
    raise AssertionError(f"No launch candidate available from {targets!r}")


# AT-SPI action names that represent a primary click in order of preference.
_ATSPI_CLICK_ACTIONS = ("click", "press", "activate")


def atspi_click(node) -> None:
    """Activate a widget via AT-SPI action API (no ponytail / Wayland injection).

    Tries "click", "press", and "activate" actions in order. Falls back to the
    coordinate-based node.click() only for non-container runs (X11 / local) where
    ponytail or XTest is available. In container mode (Wayland + no ponytail),
    raises RuntimeError with available actions for diagnosis.
    """
    try:
        available = node.actions or {}
    except Exception:  # noqa: BLE001
        available = {}
    for action in _ATSPI_CLICK_ACTIONS:
        if action in available:
            try:
                node.do_action_named(action)
                return
            except Exception:  # noqa: BLE001
                pass
    if _IN_CONTAINER:
        raise RuntimeError(
            f"atspi_click: no usable AT-SPI action on {node!r}; "
            f"available={list(available)!r}"
        )
    node.click()
