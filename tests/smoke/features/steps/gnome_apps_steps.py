"""Custom step definitions for GNOME app launch smoke tests."""
import os
import subprocess
from time import monotonic, sleep

from tests.shared.ssh_config import ssh_argv

from behave import step
try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]
try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass
from app_support import launch_background, launch_target_available

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")


def _skip_if_no_atspi(context) -> bool:
    """Skip the current scenario if AT-SPI (dogtail) is unavailable. Returns True if skipped."""
    if tree is None:
        try:
            context.scenario.skip("AT-SPI unavailable: dogtail not imported in this environment")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


FRAME_ROLES = {"frame", "filler"}
PTYXIS_APP_NAMES = ("ptyxis", "Ptyxis")
# GNOME 50 changed the Ptyxis window title from "Ptyxis" to "Terminal"; bash prompt titles
# like "user@host:~" are also accepted when window_names is empty or contains shell tokens.
PTYXIS_WINDOW_NAMES: set[str] = set()
FILES_APP_NAMES = ("org.gnome.Nautilus", "Files", "nautilus")
MISSION_CENTER_APP_NAMES = (
    "Mission Center",
    "MissionCenter",
    "io.missioncenter.MissionCenter",
)
MISSION_CENTER_LAUNCH_TARGETS = (
    ("desktop", "io.missioncenter.MissionCenter.desktop"),
    ("flatpak", "io.missioncenter.MissionCenter"),
)
EXTENSION_MANAGER_APP_NAMES = (
    "Extension Manager",
    "ExtensionManager",
    "com.mattjakeman.ExtensionManager",
)
EXTENSION_MANAGER_LAUNCH_TARGETS = (
    ("desktop", "com.mattjakeman.ExtensionManager.desktop"),
    ("flatpak", "com.mattjakeman.ExtensionManager"),
)
WAREHOUSE_APP_NAMES = ("Warehouse", "io.github.flattool.Warehouse")
WAREHOUSE_LAUNCH_TARGETS = (
    ("desktop", "io.github.flattool.Warehouse.desktop"),
    ("flatpak", "io.github.flattool.Warehouse"),
)
IMPRESSION_APP_NAMES = ("Impression", "io.gitlab.adhami3310.Impression")
IMPRESSION_LAUNCH_TARGETS = (
    ("desktop", "io.gitlab.adhami3310.Impression.desktop"),
    ("flatpak", "io.gitlab.adhami3310.Impression"),
)
CLOCKS_APP_NAMES = ("org.gnome.clocks", "Clocks")
CLOCKS_LAUNCH_TARGETS = (
    ("desktop", "org.gnome.clocks.desktop"),
    ("flatpak", "org.gnome.clocks"),
)
WEATHER_APP_NAMES = ("org.gnome.Weather", "Weather", "gnome-weather")
WEATHER_LAUNCH_TARGETS = (
    ("desktop", "org.gnome.Weather.desktop"),
    ("flatpak", "org.gnome.Weather"),
)
CALENDAR_APP_NAMES = ("org.gnome.Calendar", "Calendar", "gnome-calendar")
CALENDAR_LAUNCH_TARGETS = (
    ("desktop", "org.gnome.Calendar.desktop"),
    ("flatpak", "org.gnome.Calendar"),
)
DECIBELS_APP_NAMES = ("org.gnome.Decibels", "Decibels")
DECIBELS_LAUNCH_TARGETS = (
    ("desktop", "org.gnome.Decibels.desktop"),
    ("flatpak", "org.gnome.Decibels"),
)

# Map app name fragments → WM class substrings for Shell.Eval force-close.
# GNOME 50 apps (Ptyxis, Settings, Files) run as background daemons and
# don't terminate on Alt+F4 — we must force-delete via mutter.
_APP_WM_CLASS_HINTS: dict[str, str] = {
    "ptyxis": "ptyxis",
    "nautilus": "nautilus",
    "gnome.nautilus": "nautilus",
    "gnome-control-center": "gnome-control-center",
    "org.gnome.settings": "gnome-control-center",
}


def _shell_eval_force_close(app_names: tuple[str, ...]) -> None:
    """Force-close via mutter any windows matching app_names WM class fragments."""
    import shlex
    wm_hints: set[str] = set()
    for name in app_names:
        for key, hint in _APP_WM_CLASS_HINTS.items():
            if key in name.lower():
                wm_hints.add(hint)
    if not wm_hints:
        return
    checks = " || ".join(f"wc.includes('{h}')" for h in wm_hints)
    js = (
        "global.context.unsafe_mode = true; "
        "global.get_window_actors().forEach(a => {"
        "  try {"
        f"    const wc = (a.meta_window.get_wm_class() || '').toLowerCase();"
        f"    if ({checks}) a.meta_window.delete(global.get_current_time());"
        "  } catch(e) {}"
        "});"
    )
    if _IN_CONTAINER:
        # Must route via SSH — container cannot connect to the VM's session bus.
        cmd = (
            "source /tmp/session.env 2>/dev/null; "
            "gdbus call --session "
            "--dest org.gnome.Shell "
            "--object-path /org/gnome/Shell "
            "--method org.gnome.Shell.Eval "
            + shlex.quote(js)
        )
        subprocess.run(_ssh_args() + [cmd], capture_output=True, text=True, timeout=5)
    else:
        subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.gnome.Shell",
             "--object-path", "/org/gnome/Shell",
             "--method", "org.gnome.Shell.Eval",
             js],
            capture_output=True, text=True, timeout=5,
        )
    sleep(0.2)  # ponytail: brief settle for mutter delete; _wait_for_app_to_close polls the rest


def _ssh_args() -> list[str]:
    """Canonical SSH argv — see tests/shared/ssh_config.py."""
    return ssh_argv()


def _launch_app(app_id: str) -> None:
    """Launch a GNOME app by ID, trying multiple invocation methods.

    When running inside the runner container, desktop files are absent from the
    container filesystem.  Forward the launch to the VM via SSH so gio/gtk-launch
    can resolve the .desktop file from /usr/share/applications/.

    GNOME 50 / GLib 2.82+ requires an absolute path to the .desktop file rather
    than resolving by application ID via XDG_DATA_DIRS.
    """
    if _IN_CONTAINER:
        desktop = f"/usr/share/applications/{app_id}.desktop"
        cmd = (
            f"source /tmp/session.env 2>/dev/null; "
            f"nohup gio launch {desktop} </dev/null &>/dev/null & disown"
        )
        result = subprocess.run(
            _ssh_args() + [cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            sleep(1)  # D-Bus activation settle: app must register with AT-SPI before polling begins
            return
        raise AssertionError(
            f"Failed to launch {app_id!r} via SSH: {result.stderr.strip() or result.stdout.strip()}"
        )

    attempts = [
        ["gio", "launch", f"/usr/share/applications/{app_id}.desktop"],
        ["gtk-launch", app_id],
        ["gio", "launch", f"{app_id}.desktop"],
        ["gio", "launch", app_id],
    ]
    last_cmd: list[str] = []
    last_err = ""
    for cmd in attempts:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        last_cmd = cmd
        last_err = result.stderr.strip() or result.stdout.strip()
        if result.returncode == 0:
            sleep(1)  # D-Bus activation settle: app must register with AT-SPI before polling begins
            return
    raise AssertionError(
        f"Failed to launch {app_id!r}: last command {last_cmd!r} rc=1 — {last_err}"
    )


def _app(app_names: tuple[str, ...], label: str):
    """Take one application snapshot; the window waiter owns all retries."""
    for app in tree.root.applications():
        name = getattr(app, "name", None) or (app.get_name() if hasattr(app, "get_name") else None)
        if isinstance(name, str):
            clean = name.strip("'\" ")
            if clean in app_names or any(a.lower() in clean.lower() for a in app_names):
                return app
    raise AssertionError(f"{label} application was not found via AT-SPI")


def _wait_for_window(
    app_names: tuple[str, ...],
    window_names: set[str],
    label: str,
    timeout: float = 15,
    *,
    title_fallback: bool = False,
):
    """Poll single-shot discovery under one elapsed-time budget, including fallback."""
    deadline = monotonic() + timeout
    last_frames = []
    last_title_frames = []

    def _role(n):
        return getattr(n, "roleName", None) or (n.get_role_name() if hasattr(n, "get_role_name") else "")

    def _is_visible_frame(n):
        return _role(n) in FRAME_ROLES and getattr(n, "showing", True)

    def _name(n):
        return (getattr(n, "name", "") or (n.get_name() if hasattr(n, "get_name") else "")).strip()

    while monotonic() < deadline:
        try:
            app = _app(app_names, label)
        except Exception:  # noqa: BLE001
            app = None
        if app is not None and monotonic() < deadline:
            frames = app.findChildren(_is_visible_frame)
            last_frames = [(_name(frame), _role(frame)) for frame in frames]
            for frame in frames:
                name = _name(frame)
                if not window_names or name in window_names or "~" in name or "@" in name:
                    return frame

        if title_fallback and monotonic() < deadline:
            frames = tree.root.findChildren(_is_visible_frame)
            last_title_frames = [(_name(frame), _role(frame)) for frame in frames[:20]]
            for frame in frames:
                if _name(frame) in window_names:
                    return frame

        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.2 if title_fallback else 0.5, remaining))

    detail = ""
    if title_fallback:
        detail = (
            f". Also failed to find a visible {label} frame by title. "
            f"Visible frames: {last_title_frames}"
        )
    raise AssertionError(
        f"Visible {label} window not found. Visible frames: {last_frames}{detail}"
    )


def _wait_for_window_or_title(
    app_names: tuple[str, ...],
    window_names: set[str],
    label: str,
    timeout: float = 15,
):
    return _wait_for_window(
        app_names, window_names, label, timeout=timeout, title_fallback=True
    )


def _wait_for_app_to_close(app_names: tuple[str, ...], label: str) -> None:
    for _ in range(20):
        running = False
        try:
            if callable(getattr(tree.root, "applications", None)):
                for app in tree.root.applications():
                    name = getattr(app, "name", None) or (app.get_name() if hasattr(app, "get_name") else None)
                    if isinstance(name, str):
                        clean = name.strip("'\" ")
                        if clean in app_names or any(a.lower() in clean.lower() for a in app_names):
                            running = True
                            break
        except Exception:  # noqa: BLE001
            pass
        if not running and hasattr(tree.root, "applications") and not type(tree.root.applications).__name__.startswith("MagicMock"):
            return

        for name in app_names:
            try:
                found = getattr(tree.root, "findChild", lambda *a, **kw: None)(
                    lambda n: (getattr(n, "name", "") or "").strip("'\" ") == name,
                    recursive=False,
                    retry=False,
                )
                app = found if found is not None else tree.root.application(name)
                frames = app.findChildren(
                    lambda n: (getattr(n, "roleName", None) or getattr(n, "get_role_name", lambda: "")()) in FRAME_ROLES and getattr(n, "showing", True)
                )
                if frames:
                    running = True
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            return
        sleep(0.5)
    raise AssertionError(f"{label} is still visible in the AT-SPI tree")


def _wait_for_app_or_window_to_close(
    app_names: tuple[str, ...],
    window_names: set[str],
    label: str,
) -> None:
    try:
        _wait_for_app_to_close(app_names, label)
        return
    except AssertionError:
        pass
    for _ in range(20):
        frames = []
        try:
            def _is_frame(n):
                role = getattr(n, "roleName", None) or (n.get_role_name() if hasattr(n, "get_role_name") else "")
                name = (getattr(n, "name", "") or (n.get_name() if hasattr(n, "get_name") else "")).strip()
                showing = getattr(n, "showing", True)
                return role in FRAME_ROLES and showing and name in window_names

            frames = tree.root.findChildren(_is_frame)
        except Exception:  # noqa: BLE001
            pass
        if not frames:
            return
        sleep(0.5)
    raise AssertionError(f"{label} is still visible in the AT-SPI tree")


def _launch_assert_and_close(
    context,
    app_id: str,
    app_names: tuple[str, ...],
    window_names: set[str],
    label: str,
) -> None:
    _launch_app(app_id)
    window = _wait_for_window(app_names, window_names, label)
    context.last_launched_app_window = window
    try:
        window.click()
    except Exception:  # noqa: BLE001
        pass
    context.execute_steps('* Key combo: "<Alt><F4>" with uinput')
    # GNOME 50 apps (Ptyxis, Files, Settings) run as background daemons and
    # don't quit on Alt+F4.  Force-delete the window via mutter so the test
    # environment is clean for subsequent scenarios.
    _shell_eval_force_close(app_names)
    # Nautilus also needs --quit to stop its background service process.
    if "nautilus" in app_id.lower() or any("nautilus" in n.lower() for n in app_names):
        if _IN_CONTAINER:
            subprocess.run(
                _ssh_args() + ["source /tmp/session.env 2>/dev/null; nautilus --quit 2>/dev/null || true"],
                capture_output=True, text=True, timeout=10,
            )
        else:
            subprocess.run(["nautilus", "--quit"], capture_output=True, text=True, timeout=5)
    _wait_for_app_to_close(app_names, label)


def _launch_targets_assert_and_close(
    context,
    launch_targets: tuple[tuple[str, str], ...],
    app_names: tuple[str, ...],
    window_names: set[str],
    label: str,
) -> None:
    if not launch_target_available(launch_targets):
        try:
            context.scenario.skip(f"{label} is not installed — skipping launch test")
        except Exception:  # noqa: BLE001
            pass
        return
    context.last_launch_target = launch_background(launch_targets)
    window = _wait_for_window_or_title(app_names, window_names, label)
    context.last_launched_app_window = window
    try:
        window.click()
    except Exception:  # noqa: BLE001
        pass
    context.execute_steps('* Key combo: "<Alt><F4>" with uinput')
    _wait_for_app_or_window_to_close(app_names, window_names, label)


@step("the Ptyxis terminal launches successfully")
def ptyxis_terminal_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_assert_and_close(
        context,
        "org.gnome.Ptyxis",
        PTYXIS_APP_NAMES,
        PTYXIS_WINDOW_NAMES,
        "Ptyxis",
    )


@step("the Files file manager launches successfully")
def files_file_manager_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_assert_and_close(
        context,
        "org.gnome.Nautilus",
        FILES_APP_NAMES,
        {"Files", "Home"},
        "Files",
    )


@step("the Mission Center app launches successfully")
def mission_center_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        MISSION_CENTER_LAUNCH_TARGETS,
        MISSION_CENTER_APP_NAMES,
        {"Mission Center"},
        "Mission Center",
    )


@step("the Extension Manager app launches successfully")
def extension_manager_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        EXTENSION_MANAGER_LAUNCH_TARGETS,
        EXTENSION_MANAGER_APP_NAMES,
        {"Extension Manager"},
        "Extension Manager",
    )


@step("the Warehouse app launches successfully")
def warehouse_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        WAREHOUSE_LAUNCH_TARGETS,
        WAREHOUSE_APP_NAMES,
        {"Warehouse"},
        "Warehouse",
    )


@step("the Impression app launches successfully")
def impression_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        IMPRESSION_LAUNCH_TARGETS,
        IMPRESSION_APP_NAMES,
        {"Impression"},
        "Impression",
    )


@step("the Clocks app launches successfully")
def clocks_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        CLOCKS_LAUNCH_TARGETS,
        CLOCKS_APP_NAMES,
        {"Clocks"},
        "Clocks",
    )


@step("the Weather app launches successfully")
def weather_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        WEATHER_LAUNCH_TARGETS,
        WEATHER_APP_NAMES,
        {"Weather"},
        "Weather",
    )


@step("the Calendar app launches successfully")
def calendar_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        CALENDAR_LAUNCH_TARGETS,
        CALENDAR_APP_NAMES,
        {"Calendar"},
        "Calendar",
    )


@step("the Decibels app launches successfully")
def decibels_launches_successfully(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _launch_targets_assert_and_close(
        context,
        DECIBELS_LAUNCH_TARGETS,
        DECIBELS_APP_NAMES,
        {"Decibels"},
        "Decibels",
    )
