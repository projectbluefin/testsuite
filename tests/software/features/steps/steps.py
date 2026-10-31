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
# GTK4 maps the search bar's search_box role to AT-SPI `entry`.
BAZAAR_SEARCH_FIELD_ROLE = "entry"
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


def _welcome_skip_buttons() -> list:
    for app in tree.root.applications():
        if _name(app) == "gnome-shell":
            return app.findChildren(
                lambda n: n.showing and n.roleName in {"push button", "button"}
                and _name(n).casefold() == "skip"
            )
    return []


def dismiss_bluefin_welcome_dialog(timeout: float = 5) -> None:
    """Close Bluefin's first-run "Welcome to Bluefin" Shell modal if it is up.

    The modal grabs the keyboard, so uinput keys never reach Bazaar behind it
    (run 41196660163). Its St buttons expose no AT-SPI actions (run 41199678665),
    but gnome-shell's WelcomeDialog binds Skip to Escape
    (js/ui/welcomeDialog.js: ``key: Clutter.KEY_Escape``), and the modal holds the
    keyboard grab, so one uinput Escape is the supported dismissal. The Skip
    button is the presence probe and must be gone afterwards.
    """
    if not _welcome_skip_buttons():
        return
    from qecore.utility import keyboard_key_input

    _uinput_keyboard_ready()
    keyboard_key_input("ESC")
    _poll("Bluefin welcome dialog dismissed", timeout, lambda: not _welcome_skip_buttons())


# qecore 4.19.3 creates its python-uinput keyboard on the first key (utility.py
# _get_uinput_device: uinput.Device(all_keys), default name "python-uinput") and
# sleeps only 0.5 s before emitting. Mutter had not added the device yet, so
# that first key was lost: the welcome modal's Escape (hook_error) and the "f"
# of "flatseal" (the field showed "latseal", run 41216246249). Create the
# device up front and wait until the Shell's seat lists it.
_UINPUT_KEYBOARD_IN_SEAT_JS = """(() => global.stage.context.get_backend()
    .get_default_seat().list_devices()
    .some(device => device.get_device_name() === 'python-uinput'))()"""


def _uinput_keyboard_ready(timeout: float = 10) -> None:
    from qecore.utility import _get_uinput_device

    _get_uinput_device()
    _poll("python-uinput keyboard in the GNOME Shell seat", timeout,
          lambda: _shell_eval_bool(_UINPUT_KEYBOARD_IN_SEAT_JS))


def _bazaar_has_keyboard_focus():
    window = _visible_bazaar_window()
    if not window.active:
        raise LookupError("the Bazaar window is not the active window")
    return window


@step("Bazaar window has keyboard focus")
def bazaar_window_has_keyboard_focus(context) -> None:
    """Gate uinput keys: they go to whichever window is active."""
    if _skip_if_no_atspi(context):
        return
    _poll("Active Bazaar window", 5, _bazaar_has_keyboard_focus)
    _uinput_keyboard_ready()


# Main.activateWindow() is the Shell's own "bring this window forward" path
# (dash, alt-tab): it activates the MetaWindow on its workspace and hides the
# overview. A window mapped from an SSH-launched Flatpak carries no activation
# token, so mutter may leave focus elsewhere (run 41210513366).
_ACTIVATE_BAZAAR_JS = f"""(() => {{
    const win = global.get_window_actors().map(actor => actor.get_meta_window()).find(w =>
        w && w.get_title() === 'Bazaar' &&
        [w.get_gtk_application_id(), w.get_wm_class()].includes({BAZAAR_APP_ID!r}));
    if (!win)
        return false;
    Main.activateWindow(win);
    return true;
}})()"""


def _shell_eval_bool(js: str) -> bool:
    # Lazy: the shared module imports behave.runner and registers Shell steps,
    # which the CLI-only step modules and their unit tests do not need.
    from tests.shared.gnome_shell_steps import _eval_bool

    return _eval_bool(js)


@step("Focus the Bazaar window")
def focus_the_bazaar_window(context) -> None:
    """Activate Bazaar through GNOME Shell, then require AT-SPI to agree."""
    if _skip_if_no_atspi(context):
        return
    _bazaar_window()
    assert _shell_eval_bool(_ACTIVATE_BAZAAR_JS), "GNOME Shell has no Bazaar MetaWindow to activate"
    bazaar_window_has_keyboard_focus(context)


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

    # BzSearchBar is a GtkEditable delegate with accessible-role search_box,
    # which GTK4 exposes as an AT-SPI `entry` carrying the Text interface. Its
    # inner GtkText has role NONE and is not in the tree. Run 41201865894 typed
    # "flatseal" into the field, but the old `text`-role lookup matched nothing.
    def field():
        entries = _bazaar_view("Search").findChildren(
            lambda n: n.roleName == BAZAAR_SEARCH_FIELD_ROLE and n.showing
        )
        for node in entries:
            if node.text == query:
                return node
        raise LookupError(
            f"no showing Search {BAZAAR_SEARCH_FIELD_ROLE} contains {query!r}; "
            f"found {[node.text for node in entries]}"
        )

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
    focus_the_bazaar_window(context)
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


# Parsed with the image's own libyaml through ctypes: Utah ships libyaml-0.so.2
# but no python3-pyyaml (run 41216246249: ModuleNotFoundError: yaml), so the
# check needs nothing beyond python3's stdlib and the shared library.
# Offsets are libyaml 0.2 on LP64: yaml_parser_t.problem at 8 and
# problem_mark.line at 40; yaml_node_t.type at 0 and data.mapping.pairs
# start/top at 16/32. YAML_MAPPING_NODE is 3.
_BAZAAR_YAML_CHECK = """\
import ctypes, glob, sys
lib = ctypes.CDLL('libyaml-0.so.2')
lib.yaml_document_get_root_node.restype = ctypes.c_void_p
files = sorted(glob.glob(sys.argv[1] + '/*.yaml'))
if not files:
    sys.exit('no *.yaml files in ' + sys.argv[1])
def roots(data):
    parser = ctypes.create_string_buffer(8192)
    assert lib.yaml_parser_initialize(parser)
    lib.yaml_parser_set_input_string(parser, data, ctypes.c_size_t(len(data)))
    try:
        while True:
            document = ctypes.create_string_buffer(1024)
            if not lib.yaml_parser_load(parser, document):
                problem = ctypes.c_char_p.from_buffer(parser, 8).value or b'?'
                line = ctypes.c_size_t.from_buffer(parser, 40).value + 1
                raise ValueError(problem.decode() + ' at line ' + str(line))
            root = lib.yaml_document_get_root_node(document)
            if root:
                yield (ctypes.c_int.from_address(root).value,
                       ctypes.c_void_p.from_address(root + 16).value,
                       ctypes.c_void_p.from_address(root + 32).value)
            lib.yaml_document_delete(document)
            if not root:
                return
    finally:
        lib.yaml_parser_delete(parser)
for path in files:
    with open(path, 'rb') as handle:
        data = handle.read()
    try:
        docs = list(roots(data))
    except ValueError as exc:
        sys.exit(path + ': ' + str(exc))
    if len(docs) != 1:
        sys.exit(path + ' holds ' + str(len(docs)) + ' YAML documents, expected 1')
    kind, start, top = docs[0]
    if kind != 3 or start == top:
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
