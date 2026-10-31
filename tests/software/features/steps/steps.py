"""Custom step definitions for software suite."""

import os
import shlex
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
from tests.shared.app_support import atspi_click, launch_background

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")
BAZAAR_APP_ID = "io.github.kolunmi.Bazaar"
# GTK4 publishes g_get_prgname() as the AT-SPI application name, and
# g_application_run() sets it to basename(argv[0]); bazaar-daemon execs
# /app/bin/bazaar. The app ID is accepted in case a build sets prgname to it.
BAZAAR_A11Y_NAMES = {"bazaar", BAZAAR_APP_ID.casefold()}
FRAME_ROLES = {"frame", "filler"}
BAZAAR_WINDOW_NAMES = {"Bazaar"}
BAZAAR_TAB_NAMES = {"Curated", "Explore", "Library", "Search"}
BAZAAR_TAB_ROLES = {"page tab", "toggle button"}
# libadwaita exposes each AdwViewStackPage as a `panel` named after its title.
BAZAAR_VIEW_ROLE = "panel"
POLL_INTERVAL = 0.25


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


def _poll(what: str, timeout: float, probe):
    """Return ``probe()``'s first truthy result within ``timeout`` seconds.

    Probes must make single AT-SPI queries (never dogtail's retrying
    ``root.application()``, which blocks ~10s per miss) so the deadline holds.
    Exceptions count as "not yet": AT-SPI cache drops raise mid-query.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = probe()
            if result:
                return result
            last = "probe returned nothing"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"{what} not reached within {timeout}s: {last}")
        sleep(POLL_INTERVAL)


def _name(node) -> str:
    return (node.name or "").strip()


def _bazaar_app():
    apps = list(tree.root.applications())
    for app in apps:
        if _name(app).casefold() in BAZAAR_A11Y_NAMES:
            return app
    raise LookupError(f"Bazaar is not an AT-SPI application; found {sorted(_name(a) for a in apps)}")


def _visible_bazaar_window():
    frames = [n for n in _bazaar_app().children if n.roleName in FRAME_ROLES and n.showing]
    for frame in frames:
        if _name(frame) in BAZAAR_WINDOW_NAMES:
            return frame
    raise LookupError(f"no visible Bazaar window; visible frames: {[(_name(f), f.roleName) for f in frames]}")


def _bazaar_window(timeout: float = 30):
    return _poll("Visible Bazaar window", timeout, _visible_bazaar_window)


def _bazaar_tab(window, name: str):
    for tab in window.findChildren(
        lambda n: n.roleName in BAZAAR_TAB_ROLES and n.showing and _name(n).casefold() == name.casefold()
    ):
        return tab
    raise LookupError(f"Bazaar tab {name!r} is not showing")


def _bazaar_tab_is_selected(tab) -> bool:
    for attr in ("selected", "checked"):
        try:
            if bool(getattr(tab, attr)):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _shown_bazaar_view(window):
    """Return ``(name, panel)`` for the Bazaar view that is showing content.

    Only the visible AdwViewStack page has showing widgets, and while Bazaar
    is Refreshing no page does, so header-bar chrome cannot satisfy this.
    """
    for panel in window.findChildren(
        lambda n: n.roleName == BAZAAR_VIEW_ROLE and _name(n) in BAZAAR_TAB_NAMES
    ):
        if panel.findChildren(lambda n: n.showing):
            return _name(panel), panel
    raise LookupError("no Bazaar view is showing content (still Refreshing?)")


def _bazaar_view(name: str):
    window = _visible_bazaar_window()
    shown, panel = _shown_bazaar_view(window)
    if shown.casefold() != name.casefold():
        raise LookupError(f"Bazaar shows view {shown!r}, not {name!r}")
    if not _bazaar_tab_is_selected(_bazaar_tab(window, name)):
        raise LookupError(f"Bazaar tab {name!r} is not selected")
    return panel


def _bazaar_flatpak_is_running(context) -> bool:
    result = _flatpak(context, ["ps", "--columns=application"], timeout=15)
    assert result.returncode == 0, (
        f"flatpak ps failed (rc={result.returncode}): {result.stderr.strip()}"
    )
    apps = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip().lower() != "application"
    }
    return BAZAAR_APP_ID in apps


def _bazaar_gone(context) -> bool:
    try:
        _visible_bazaar_window()
    except LookupError:
        return not _bazaar_flatpak_is_running(context)
    return False


def _wait_for_bazaar_to_close(context, timeout: float = 15) -> None:
    _poll("Bazaar window closed and Bazaar Flatpak exited", timeout, lambda: _bazaar_gone(context))


@step("Launch Bazaar")
def launch_bazaar(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_launch_target = launch_background((("flatpak", BAZAAR_APP_ID),))


@step("Bazaar main window is accessible")
def bazaar_main_window_is_accessible(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_window = _bazaar_window()


@step("Bazaar main content is loaded")
def bazaar_main_content_is_loaded(context) -> None:
    if _skip_if_no_atspi(context):
        return
    # First launch refreshes Flathub metadata behind the Refreshing page.
    _poll("Bazaar view with content", 120, lambda: _shown_bazaar_view(_visible_bazaar_window()))


@step('Bazaar tab "{name}" is accessible')
def bazaar_tab_is_accessible(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_tab = _poll(
        f"Bazaar tab {name!r}", 15, lambda: _bazaar_tab(_visible_bazaar_window(), name)
    )


@step('Activate Bazaar tab "{name}"')
def activate_bazaar_tab(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return

    def click():
        tab = _bazaar_tab(_visible_bazaar_window(), name)
        atspi_click(tab)
        return tab

    context.bazaar_tab = _poll(f"Activated Bazaar tab {name!r}", 15, click)


@step('Bazaar view "{name}" is loaded')
def bazaar_view_is_loaded(context, name: str) -> None:
    if _skip_if_no_atspi(context):
        return
    context.bazaar_view = _poll(f"Bazaar view {name!r} with content", 30, lambda: _bazaar_view(name))


@step('Bazaar search field shows "{query}"')
def bazaar_search_field_shows(context, query: str) -> None:
    if _skip_if_no_atspi(context):
        return

    def field():
        for node in _bazaar_view("Search").findChildren(lambda n: n.roleName == "text" and n.showing):
            if node.text == query:
                return node
        raise LookupError(f"no showing Search text field contains {query!r}")

    _poll(f"Bazaar search field text {query!r}", 15, field)


@step('Bazaar search results include "{title}"')
def bazaar_search_results_include(context, title: str) -> None:
    if _skip_if_no_atspi(context):
        return

    def result():
        for node in _bazaar_view("Search").findChildren(lambda n: n.roleName == "label" and n.showing):
            if _name(node) == title:
                return node
        raise LookupError(f"no showing Search result labelled {title!r}")

    _poll(f"Bazaar search result {title!r}", 60, result)


@step("Close Bazaar via shortcut")
def close_bazaar_via_shortcut(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _bazaar_window()
    # <primary>q is app.quit, which also tells bazaar-daemon to Quit. qecore
    # builds KEY_<NAME> from each token, so modifiers need evdev names.
    context.execute_steps('* Key combo: "<LEFTCTRL><Q>" with uinput')
    _wait_for_bazaar_to_close(context)


@step("Bazaar is no longer running")
def bazaar_is_no_longer_running(context) -> None:
    if _skip_if_no_atspi(context):
        return
    _wait_for_bazaar_to_close(context)


@step('No coredump entries exist on the VM for "{name}"')
def no_vm_coredump_entries_exist(context, name: str) -> None:
    result = _run_in_session(context, f"coredumpctl list --no-pager --no-legend {shlex.quote(name)}")
    # coredumpctl exits 1 when nothing matches and 0 when it lists entries.
    assert result.returncode in (0, 1), (
        f"coredumpctl failed (rc={result.returncode}): {result.stderr.strip()}"
    )
    assert result.returncode == 1, f"Unexpected coredump entries for {name}:\n{result.stdout.strip()}"


_BAZAAR_YAML_CHECK = """\
import glob, sys, yaml
files = sorted(glob.glob(sys.argv[1] + '/*.yaml'))
if not files:
    sys.exit('no *.yaml files in ' + sys.argv[1])
for path in files:
    with open(path) as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not data:
        sys.exit(path + ' is not a non-empty YAML mapping')
    print(path)
"""


@step('Bazaar YAML configuration files in "{directory}" parse as non-empty mappings')
def bazaar_yaml_files_parse(context, directory: str) -> None:
    result = _run_in_session(
        context, f"python3 -c {shlex.quote(_BAZAAR_YAML_CHECK)} {shlex.quote(directory)}"
    )
    assert result.returncode == 0, (
        f"Bazaar YAML check failed (rc={result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )


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
