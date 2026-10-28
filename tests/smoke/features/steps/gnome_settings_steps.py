"""Custom step definitions for GNOME Settings smoke tests."""
import os
import shutil
import subprocess
from time import sleep

from behave import step
try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]
try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass
from app_support import launch_background


def _skip_if_no_atspi(context) -> bool:
    if tree is None:
        try:
            context.scenario.skip("AT-SPI unavailable: dogtail not imported in this environment")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


SETTINGS_APP_NAMES = ("gnome-control-center", "Settings")
SETTINGS_A11Y_ENV = {
    "XDG_CURRENT_DESKTOP": "GNOME",
    "GNOME_ACCESSIBILITY": "1",
    "AT_SPI_BUS_ADDRESS": os.environ.get(
        "AT_SPI_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/at-spi/bus"
    ),
}
SETTINGS_LAUNCH_TARGETS = (
    ("command", "gnome-control-center"),
    ("desktop", "org.gnome.Settings.desktop"),
)
TEXT_ROLES = {"heading", "label", "static", "text", "description", "paragraph"}
# Provider titles GNOME Online Accounts lists; none appear in the Settings sidebar.
GOA_PROVIDER_LABELS = ("Google", "Nextcloud", "Microsoft", "Email Server", "WebDAV", "Kerberos")
INFO_TOKENS = ("bluefin", "fedora", "linux", "version", "os")
SETTINGS_PANEL_ALIASES = {
    "About": ("About", "System"),
    "Displays": ("Displays",),
    "Privacy & Security": ("Privacy & Security", "Privacy"),
}
# Maps display panel name → gnome-control-center CLI panel ID.
# gnome-control-center <panel-id> navigates directly to the panel via D-Bus
# activation, avoiding the need to click sidebar items via AT-SPI.
SETTINGS_PANEL_IDS = {
    "About": "system",
    "Displays": "display",
    "Wi-Fi": "wifi",
    "Privacy & Security": "privacy",
    "Notifications": "notifications",
    "Keyboard": "keyboard",
    "Power": "power",
    "Accessibility": "universal-access",
    "Sound": "sound",
    "Network": "network",
    "Bluetooth": "bluetooth",
    "Users": "user-accounts",
}


def _settings_app(timeout: int = 15):
    """Find the Settings app in the AT-SPI tree, retrying for up to ``timeout`` seconds."""
    import time
    deadline = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            if callable(getattr(tree.root, "applications", None)):
                for app in tree.root.applications():
                    name = getattr(app, "name", None) or (app.get_name() if hasattr(app, "get_name") else None)
                    if isinstance(name, str):
                        clean = name.strip("'\" ")
                        if clean in SETTINGS_APP_NAMES or "settings" in clean.lower() or "control-center" in clean.lower():
                            return app
        except Exception:  # noqa: BLE001
            pass
        for name in SETTINGS_APP_NAMES:
            try:
                return tree.root.application(name)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if time.monotonic() >= deadline:
            break
        sleep(0.5)
    for name in SETTINGS_APP_NAMES:
        try:
            return tree.root.application(name)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise AssertionError(f"GNOME Settings application was not found via AT-SPI after {timeout}s: {last_error}")


def _settings_window(timeout: int = 10):
    app = _settings_app()
    def _is_frame(n):
        role = getattr(n, "roleName", None) or (n.get_role_name() if hasattr(n, "get_role_name") else "")
        showing = getattr(n, "showing", True)
        return role in {"frame", "filler"} and showing

    for _ in range(timeout * 2):
        frames = app.findChildren(_is_frame)
        if frames:
            return frames[0]
        sleep(0.5)
    raise AssertionError("Visible GNOME Settings window not found")


@step("Launch Settings via command")
def launch_settings_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    # Kill any pre-running daemon — it may have started before toolkit-accessibility
    # was enabled and therefore won't be registered with AT-SPI. The fresh launch
    # via gio will start a new instance that properly registers.
    from app_support import _IN_CONTAINER, _ssh_run
    if _IN_CONTAINER:
        # Use exact-name pkill to avoid killing unrelated processes.
        # pkill -f with a broad pattern can crash the GNOME session on GNOME 50.
        _ssh_run(
            "pkill -TERM -x gnome-control-c 2>/dev/null; sleep 0.5; true",
            timeout=5,
        )
    else:
        subprocess.run(
            ["pkill", "-9", "gnome-control-c"],
            capture_output=True, text=True,
        )
        sleep(0.5)
    context.settings_launch_target = launch_background(
        SETTINGS_LAUNCH_TARGETS, env=SETTINGS_A11Y_ENV
    )
    sleep(1.0)


@step("Settings window is accessible")
def settings_window_is_accessible(context) -> None:
    context.settings_window = _settings_window()


def _app_no_retry(name: str):
    """Look up one top-level application by exact name without dogtail's retries.

    ``tree.root.application(name)`` retries internally, so calling it per alias
    inside a poll loop multiplies the caller's timeout when the app is absent.
    Scan the single-shot ``applications()`` snapshot instead.
    """
    try:
        for app in tree.root.applications():
            if (getattr(app, "name", "") or "").strip("'\" ") == name:
                return app
    except Exception:  # noqa: BLE001
        return None
    return None


@step("Settings is no longer running")
def settings_is_no_longer_running(context) -> None:
    try:
        if shutil.which("pkill"):
            subprocess.run(
                ["pkill", "-9", "gnome-control-c"],
                capture_output=True, text=True,
            )
    except Exception:  # noqa: BLE001
        pass
    sleep(0.5)
    for _ in range(20):
        running = False
        try:
            if callable(getattr(tree.root, "applications", None)):
                for app in tree.root.applications():
                    name = getattr(app, "name", None) or (app.get_name() if hasattr(app, "get_name") else None)
                    if isinstance(name, str):
                        clean = name.strip("'\" ")
                        if clean in SETTINGS_APP_NAMES or "settings" in clean.lower() or "control-center" in clean.lower():
                            running = True
                            break
        except Exception:  # noqa: BLE001
            pass
        if not running and hasattr(tree.root, "applications") and not type(tree.root.applications).__name__.startswith("MagicMock"):
            return

        for name in SETTINGS_APP_NAMES:
            try:
                app = _app_no_retry(name)
                if app is None:
                    continue
                frames = app.findChildren(lambda n: (getattr(n, "roleName", None) or getattr(n, "get_role_name", lambda: "")()) in {"frame", "filler"} and getattr(n, "showing", True))
                if frames:
                    running = True
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            return
        sleep(0.5)
    raise AssertionError("GNOME Settings is still visible in the AT-SPI tree")


def _visible_text(node) -> str:
    name = (getattr(node, "name", "") or "").strip()
    if name:
        return name
    try:
        text = (getattr(node, "text", "") or "").strip()
    except Exception:  # noqa: BLE001
        text = ""
    return text


def _looks_like_system_info(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in INFO_TOKENS) or any(char.isdigit() for char in text)


@step("Settings sidebar is present")
def settings_sidebar_is_present(context) -> None:
    app = _settings_app()
    list_boxes = app.findChildren(
        lambda n: n.roleName in {"list box", "list"}
        and n.showing
        and (
            (n.name or "").strip().casefold() == "settings categories"
            or n.findChildren(lambda c: c.roleName in {"button", "list item"})
        )
    )
    sidebar = next(
        (
            list_box
            for list_box in list_boxes
            if list_box.findChildren(lambda n: n.roleName in {"button", "list item"})
        ),
        None,
    )
    assert sidebar is not None, "Settings sidebar list box not found"
    context.settings_sidebar = sidebar


@step('Navigate to Settings panel "{name}"')
def navigate_to_settings_panel(context, name: str) -> None:
    from app_support import _IN_CONTAINER, _ssh_launch, _ssh_run
    # Use gnome-control-center <panel-id> for direct D-Bus activation — this is more
    # reliable than AT-SPI sidebar clicks, especially in the runner container where
    # Wayland input injection via ponytail is unavailable.
    panel_id = SETTINGS_PANEL_IDS.get(name, name.lower().replace(" ", "-").replace("&", "and"))
    if _IN_CONTAINER:
        # Kill any existing instance first so the new launch opens on the correct panel.
        # -x matches the kernel comm, truncated to 15 chars ("gnome-control-c");
        # the full name never matched, so the old window kept its previous panel.
        _ssh_run(
            "pkill -TERM -x gnome-control-c 2>/dev/null; sleep 0.5; true",
            timeout=5,
        )
        # Launch gnome-control-center with the panel ID directly, detached and with
        # the a11y env (as "Launch Settings via command" does): a bare "&" over SSH
        # dies with the session and never registers on AT-SPI.
        _ssh_launch(f"gnome-control-center {panel_id}", SETTINGS_A11Y_ENV)
    else:
        try:
            if shutil.which("pkill"):
                subprocess.run(["pkill", "-9", "gnome-control-c"], capture_output=True, text=True)
        except Exception:  # noqa: BLE001
            pass
        sleep(0.5)
        local_env = {**os.environ, **SETTINGS_A11Y_ENV}
        subprocess.Popen(
            ["gnome-control-center", panel_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=local_env,
        )
    context.last_settings_panel = name


@step('Settings panel "{name}" is visible')
def settings_panel_is_visible(context, name: str) -> None:
    app = _settings_app()
    aliases = SETTINGS_PANEL_ALIASES.get(name, (name,))
    for _ in range(10):
        matches = app.findChildren(
            lambda n: n.showing
            and (n.name or "").strip() in aliases
            and n.roleName in TEXT_ROLES
        )
        if matches:
            return
        sleep(0.5)
    raise AssertionError(f"Settings panel {name!r} is not visible")


@step("About page shows system information")
def about_page_shows_system_information(context) -> None:
    app = _settings_app()
    # GNOME 50 libadwaita uses additional AT-SPI roles not in TEXT_ROLES.
    # First try with TEXT_ROLES, then fall back to all showing nodes.
    for _ in range(10):
        for role_filter in (
            lambda n: n.showing and n.roleName in TEXT_ROLES and bool(_visible_text(n)),
            lambda n: n.showing and bool(_visible_text(n)),
        ):
            visible_texts = [
                _visible_text(node)
                for node in app.findChildren(role_filter)
            ]
            matches = [text for text in visible_texts if _looks_like_system_info(text)]
            if matches:
                context.about_system_info = matches[0]
                return
        sleep(0.5)
    raise AssertionError(
        "About page did not expose visible system information text"
    )


@step("Online Accounts provider list is non-empty")
def online_accounts_provider_list_is_non_empty(context) -> None:
    # Match provider labels anywhere in the showing tree: libadwaita rows do not
    # sit under an ancestor named "Online Accounts" and may carry the title on a
    # child label rather than the row, so a role+ancestor query finds nothing
    # even when the panel lists every provider. No sidebar entry contains these.
    app = _settings_app()
    for _ in range(20):
        names = {
            (n.name or "").strip()
            for n in app.findChildren(
                lambda n: n.showing
                and any(p in (n.name or "") for p in GOA_PROVIDER_LABELS)
            )
        }
        if names:
            context.online_accounts_providers = sorted(names)
            return
        sleep(0.5)
    raise AssertionError(
        "No Online Accounts provider rows visible in the AT-SPI tree"
    )
