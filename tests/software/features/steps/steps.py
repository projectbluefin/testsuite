"""Custom step definitions for software suite."""

import os
import subprocess
import time
from time import sleep

from behave import step
try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]
from qecore.common_steps import *  # noqa: F401,F403
from tests.shared.ssh_config import ssh_argv
from tests.shared.ssh_steps import *  # noqa: F401,F403
from tests.smoke.features.steps.app_support import atspi_click, launch_background

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")
FRAME_ROLES = {"frame", "filler"}
BAZAAR_APP_NAMES = (
    "gnome-software",
    "org.gnome.Software",
    "io.github.kolunmi.Bazaar",
    "Bazaar",
)
BAZAAR_WINDOW_NAMES = {"Bazaar"}
BAZAAR_TAB_NAMES = {"Curated", "Explore", "Library", "Search"}
BAZAAR_TAB_ROLES = {"page tab", "toggle button"}
BAZAAR_LAUNCH_TARGETS = (
    ("flatpak", "io.github.kolunmi.Bazaar"),
    ("desktop", "io.github.kolunmi.Bazaar.desktop"),
    ("desktop", "org.gnome.Software.desktop"),
    ("command", "gnome-software"),
)


def _skip_if_no_atspi(context) -> bool:
    if tree is None:
        try:
            context.scenario.skip("AT-SPI unavailable: dogtail not imported in this environment")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


def _flatpak(context, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run flatpak via SSH when inside the runner container.

    Connection details come from the same source as the shared SSH steps
    (``tests.shared.ssh_config.ssh_argv``): context attributes,
    then behave userdata, then environment variables.
    """
    if _IN_CONTAINER:
        return subprocess.run(
            ssh_argv(context) + [" ".join(["flatpak"] + [f"'{a}'" for a in args])],
            capture_output=True, text=True, timeout=timeout,
        )
    return subprocess.run(
        ["flatpak"] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _run_in_session(context, cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a shell command inside the VM's GNOME session.

    Session-bus calls (portals, gdbus) need `DBUS_SESSION_BUS_ADDRESS`, which
    the runner container does not have, so the command is forwarded over SSH
    with `/tmp/session.env` sourced first.
    """
    full = f"source /tmp/session.env 2>/dev/null; {cmd}"
    if _IN_CONTAINER:
        return subprocess.run(
            ssh_argv(context) + [full],
            capture_output=True, text=True, timeout=timeout,
        )
    return subprocess.run(
        full, shell=True, capture_output=True, text=True, timeout=timeout,
    )


def _bazaar_app(context=None):
    instance = getattr(getattr(context, "software", None), "instance", None)
    if instance is not None:
        return instance
    last_error = None
    for name in BAZAAR_APP_NAMES:
        try:
            return tree.root.application(name)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise AssertionError(f"Bazaar application was not found via AT-SPI: {last_error}")


def _bazaar_window(context=None, timeout: int = 15):
    last_frames = []
    for _ in range(timeout * 5):
        try:
            app = _bazaar_app(context)
        except Exception:  # noqa: BLE001
            sleep(0.2)
            continue
        frames = app.findChildren(
            lambda n: n.roleName in FRAME_ROLES
            and n.showing
            and (n.name or "").strip() in BAZAAR_WINDOW_NAMES
        )
        if frames:
            return frames[0]
        last_frames = [
            ((frame.name or "").strip(), frame.roleName)
            for frame in app.findChildren(lambda n: n.roleName in FRAME_ROLES and n.showing)
        ]
        sleep(0.2)
    raise AssertionError(f"Visible Bazaar window not found. Visible frames: {last_frames}")


def _bazaar_tabs(window) -> list:
    return window.findChildren(
        lambda n: n.showing
        and n.roleName in BAZAAR_TAB_ROLES
        and (n.name or "").strip() in BAZAAR_TAB_NAMES
    )


def _find_bazaar_tab(context, name: str):
    window = _bazaar_window(context)
    matches = [
        node for node in _bazaar_tabs(window)
        if (node.name or "").strip().casefold() == name.casefold()
    ]
    assert matches, f"Bazaar tab {name!r} not found"
    return matches[0]


def _bazaar_tab_is_selected(tab) -> bool:
    for attr in ("selected", "checked"):
        try:
            if bool(getattr(tab, attr)):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _bazaar_has_visible_content(window) -> bool:
    descendants = window.findChildren(
        lambda n: n.showing
        and n.roleName not in FRAME_ROLES
        and (
            (n.roleName not in BAZAAR_TAB_ROLES)
            or (n.name or "").strip() not in BAZAAR_TAB_NAMES
        )
    )
    return bool(descendants)


def wait_for_bazaar_main_content(context, timeout: int = 30) -> bool:
    """Wait until Bazaar's Refreshing spinner clears and tabs are available."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            window = _bazaar_window(context, timeout=1)
            tabs = _bazaar_tabs(window)
            if tabs and _bazaar_has_visible_content(window):
                context.bazaar_window = window
                context.bazaar_tabs = tabs
                return True
        except Exception:  # noqa: BLE001
            pass
        sleep(0.2)
    return False


def _bazaar_flatpak_is_running(context) -> bool:
    result = _flatpak(context, ["ps", "--columns=application"], timeout=15)
    if result.returncode != 0:
        return False
    apps = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip().lower() != "application"
    }
    return "io.github.kolunmi.Bazaar" in apps


def _wait_for_bazaar_to_close(context, timeout: int = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        window_visible = True
        try:
            _bazaar_window(context, timeout=1)
        except Exception:  # noqa: BLE001
            window_visible = False
        if not window_visible and not _bazaar_flatpak_is_running(context):
            return
        sleep(0.2)
    raise AssertionError("Bazaar is still visible or running after close shortcut")


@step("Launch Bazaar via fallback targets")
def launch_bazaar_via_fallback_targets(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_launch_target = launch_background(BAZAAR_LAUNCH_TARGETS)


@step("Bazaar main window is accessible")
def bazaar_main_window_is_accessible(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_window = _bazaar_window(context)
    try:
        atspi_click(context.bazaar_window)
    except Exception:  # noqa: BLE001
        pass


@step("Bazaar main content is loaded")
def bazaar_main_content_is_loaded(context) -> None:
    if _skip_if_no_atspi(context):
        return
    assert wait_for_bazaar_main_content(context), (
        "Bazaar main content did not appear before timeout; loading spinner may still be active"
    )


@step('Bazaar tab "{name}" is accessible')
def bazaar_tab_is_accessible(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            tab = _find_bazaar_tab(context, name)
            assert tab.showing, f"Bazaar tab {name!r} is not showing"
            context.bazaar_tab = tab
            return
        except Exception:  # noqa: BLE001
            sleep(0.2)
    raise AssertionError(f"Bazaar tab {name!r} did not become accessible")


@step('Activate Bazaar tab "{name}"')
def activate_bazaar_tab(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            tab = _find_bazaar_tab(context, name)
            atspi_click(tab)
            context.bazaar_tab = tab
            sleep(0.2)
            return
        except Exception:  # noqa: BLE001
            sleep(0.2)
    raise AssertionError(f"Bazaar tab {name!r} could not be activated")


@step('Bazaar view "{name}" is loaded')
def bazaar_view_is_loaded(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            window = _bazaar_window(context, timeout=1)
            tab = _find_bazaar_tab(context, name)
            if _bazaar_tab_is_selected(tab) and _bazaar_has_visible_content(window):
                context.bazaar_window = window
                context.bazaar_tab = tab
                return
        except Exception:  # noqa: BLE001
            pass
        sleep(0.2)
    raise AssertionError(f"Bazaar view {name!r} did not load")


@step("Close Bazaar via shortcut")
def close_bazaar_via_shortcut(context) -> None:
    if _skip_if_no_atspi(context):
        return
    try:
        atspi_click(_bazaar_window(context))
    except Exception:  # noqa: BLE001
        pass
    for combo in ('"<Alt><F4>"', '"<Ctrl><Q>"'):
        context.execute_steps(f"* Key combo: {combo} with uinput")
        try:
            _wait_for_bazaar_to_close(context, timeout=5)
            return
        except AssertionError:
            continue
    _wait_for_bazaar_to_close(context)


@step("Bazaar is no longer running")
def bazaar_is_no_longer_running(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _wait_for_bazaar_to_close(context)


@step('Flatpak permissions table "{table}" is queryable')
def flatpak_permissions_table_is_queryable(context, table: str) -> None:
    """Assert the permission store really serves ``table``.

    `flatpak permissions <table>` exits 0 with *empty* output for a table that
    does not exist, so the return code proves nothing on its own. Validate the
    output instead: every emitted row is tab-separated and its first column is
    the table name, so rows leaking in from another table (or a usage/error
    banner) are rejected.
    """
    result = _flatpak(context, ["permissions", table])
    assert result.returncode == 0 or "No permissions" in result.stdout or "No permissions" in result.stderr, (
        f"flatpak permissions {table!r} failed unexpectedly: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    rows = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("No permissions")
    ]
    foreign = [
        row for row in rows
        if row.split("\t")[0].strip().lower() not in {table.lower(), "table"}
    ]
    assert not foreign, (
        f"flatpak permissions {table!r} emitted rows that do not belong to the "
        f"{table!r} table: {foreign}\n{result.stdout}"
    )


@step("Flatpak documents portal reports a mount point")
def flatpak_documents_portal_reports_mount_point(context) -> None:
    """Prove the documents permission table has a live backing portal.

    An empty `flatpak permissions documents` listing is indistinguishable from
    a nonexistent table, and a fresh CI VM legitimately has no document grants.
    `org.freedesktop.portal.Documents.GetMountPoint` is the assertion that
    actually fails when the portal is absent: it returns the fuse mount path
    (`/run/user/<uid>/doc`) only when the documents backend is running.
    """
    result = _run_in_session(
        context,
        "gdbus call --session --dest org.freedesktop.portal.Documents "
        "--object-path /org/freedesktop/portal/documents "
        "--method org.freedesktop.portal.Documents.GetMountPoint",
    )
    assert result.returncode == 0, (
        "Could not reach the documents portal: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "Error:" not in result.stdout and "/doc" in result.stdout, (
        "org.freedesktop.portal.Documents.GetMountPoint did not return a "
        f"document portal mount point:\n{result.stdout}\n{result.stderr}"
    )


@step('Set flatpak user override "{override}" for "{app_id}"')
def set_flatpak_user_override(context, override: str, app_id: str) -> None:
    result = _flatpak(context, ["override", "--user"] + override.split() + [app_id])
    assert result.returncode == 0, (
        f"flatpak override --user {override} {app_id} failed: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )


@step('Flatpak user override "{fragment}" is active for "{app_id}"')
def flatpak_user_override_is_active(context, fragment: str, app_id: str) -> None:
    result = _flatpak(context, ["override", "--user", "--show", app_id])
    assert result.returncode == 0, (
        f"flatpak override --show {app_id} failed: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert fragment in result.stdout, (
        f"Override fragment {fragment!r} not found in override output for {app_id}:\n{result.stdout}"
    )


@step('Reset flatpak user overrides for "{app_id}"')
def reset_flatpak_user_overrides(context, app_id: str) -> None:
    result = _flatpak(context, ["override", "--user", "--reset", app_id])
    assert result.returncode == 0, (
        f"flatpak override --user --reset {app_id} failed: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )


@step('No flatpak user overrides exist for "{app_id}"')
def no_flatpak_user_overrides_exist(context, app_id: str) -> None:
    result = _flatpak(context, ["override", "--user", "--show", app_id])
    # After reset, --show returns empty output (rc=0) or a minimal [Context] header.
    assert result.returncode == 0, (
        f"flatpak override --show {app_id} failed: "
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    # No override-specific keys should be present (filesystems, devices, etc.).
    # Override output is a keyfile ("filesystems=home;"), so compare the key part
    # before "=" — comparing whole lines never matches and passes falsely.
    # `--env=` overrides are recorded under [Environment] with arbitrary key
    # names, so an allow-list of [Context] keys alone reports "no overrides"
    # while environment overrides are still live. Any [Environment] entry counts.
    context_keys = {"filesystems", "devices", "features", "sockets", "shared", "persistent"}
    section = None
    found = set()
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if section == "Environment":
            found.add(f"Environment.{key}")
        elif key.lower() in context_keys:
            found.add(key.lower())
    assert not found, (
        f"Expected no user overrides for {app_id} after reset, "
        f"but found active override keys: {found}\n{result.stdout}"
    )


@step('Flatpak remote "{name}" is configured')
def flatpak_remote_is_configured(context, name: str) -> None:
    result = _flatpak(context, ['remote-list', '--columns=name'])
    assert result.returncode == 0, (
        f'flatpak remote-list failed: rc={result.returncode}\n'
        f'stdout={result.stdout}\nstderr={result.stderr}'
    )
    remotes = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert name in remotes, f'Flatpak remote {name!r} not found in {sorted(remotes)}'


@step('Flatpak app "{app_id}" is installed')
def flatpak_app_is_installed(context, app_id: str) -> None:
    result = _flatpak(context, ['list', '--app', '--columns=application'])
    assert result.returncode == 0, (
        f'flatpak list failed: rc={result.returncode}\n'
        f'stdout={result.stdout}\nstderr={result.stderr}'
    )
    apps = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert app_id in apps, f'Flatpak app {app_id!r} not found in installed apps'


@step('Flatpak app info is queryable for "{app_id}"')
def flatpak_app_info_is_queryable(context, app_id: str) -> None:
    result = _flatpak(context, ['info', app_id])
    assert result.returncode == 0, (
        f'flatpak info {app_id!r} failed: rc={result.returncode}\n'
        f'stdout={result.stdout}\nstderr={result.stderr}'
    )
    assert app_id in result.stdout, (
        f'App ID {app_id!r} not found in flatpak info output:\n{result.stdout}'
    )


@step('Flatpak app "{app_id}" is from remote "{remote}"')
def flatpak_app_is_from_remote(context, app_id: str, remote: str) -> None:
    result = _flatpak(context, ['info', app_id])
    assert result.returncode == 0, (
        f'flatpak info {app_id!r} failed: rc={result.returncode}\n'
        f'stdout={result.stdout}\nstderr={result.stderr}'
    )
    output_lower = result.stdout.lower()
    assert remote.lower() in output_lower, (
        f'Remote {remote!r} not found in flatpak info output for {app_id}:\n{result.stdout}'
    )


@step('Flatpak app "{app_id}" is not installed')
def flatpak_app_is_not_installed(context, app_id: str) -> None:
    result = _flatpak(context, ['list', '--app', '--columns=application'])
    assert result.returncode == 0, (
        f'flatpak list failed: rc={result.returncode}\n'
        f'stdout={result.stdout}\nstderr={result.stderr}'
    )
    apps = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert app_id not in apps, f'Flatpak app {app_id!r} is still installed'
