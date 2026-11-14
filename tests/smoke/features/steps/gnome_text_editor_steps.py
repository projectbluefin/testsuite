"""Custom step definitions for GNOME Text Editor smoke tests."""
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
from app_support import (
    describe_subtree,
    launch_background,
    newest_active_frame,
    stop_app_instances,
)


def _skip_if_no_atspi(context) -> bool:
    if tree is None:
        try:
            context.scenario.skip("AT-SPI unavailable: dogtail not imported in this environment")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


TEXT_EDITOR_APP_NAMES = ("gnome-text-editor", "Text Editor")
TEXT_EDITOR_LAUNCH_TARGETS = (
    ("command", "gnome-text-editor"),
    ("desktop", "org.gnome.TextEditor.desktop"),
    ("desktop", "org.gnome.TextEditor.Devel.desktop"),
)
TEXT_WIDGET_ROLES = {"text", "entry", "paragraph", "document text"}
DIALOG_ENTRY_ROLES = {"text", "entry", "document text"}
BUTTON_ROLES = {"push button", "button"}
# GTK 4 file choosers are dialogs; libadwaita's "Save Changes?" prompt is an alert.
DIALOG_ROLES = {"dialog", "alert", "file chooser"}
# A file chooser shown by another process is a top-level window there, not
# necessarily a dialog role.
PORTAL_WINDOW_ROLES = DIALOG_ROLES | {"frame", "window"}
# Text Editor keeps unsaved drafts and reopens them on the next launch.
TEXT_EDITOR_STATE_DIRS = (
    ".local/share/org.gnome.TextEditor",
    ".var/app/org.gnome.TextEditor/data/org.gnome.TextEditor",
)


def _text_editor_app():
    """Take one ``applications()`` snapshot; dogtail's per-name lookup retries internally."""
    last_error = None
    try:
        for app in tree.root.applications():
            if (getattr(app, "name", "") or "").strip("'\" ") in TEXT_EDITOR_APP_NAMES:
                return app
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    raise AssertionError(
        f"GNOME Text Editor application was not found via AT-SPI: "
        f"{last_error or f'none of {TEXT_EDITOR_APP_NAMES} registered'}"
    )


@step("Launch Text Editor via command")
def launch_text_editor_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    # Each launch of the running app opens another window, and a restarted app
    # reopens the last run's drafts; start from no windows and no drafts.
    stop_app_instances("gnome-text-edit", reset_paths=TEXT_EDITOR_STATE_DIRS)
    context.text_editor_launch_target = launch_background(TEXT_EDITOR_LAUNCH_TARGETS)


def _text_editor_window():
    app = _text_editor_app()
    frames = app.findChildren(lambda n: n.roleName in {"frame", "filler"} and n.showing)
    assert frames, "Visible GNOME Text Editor window not found"
    return newest_active_frame(frames)


def _node_text(node) -> str:
    values = []
    name = (getattr(node, "name", "") or "").strip()
    if name:
        values.append(name)
    try:
        text = (getattr(node, "text", "") or "").strip()
    except Exception:  # noqa: BLE001
        text = ""
    if text and text not in values:
        values.append(text)
    return "\n".join(values)


def _editable_text_area():
    window = _text_editor_window()
    areas = window.findChildren(
        lambda n: n.showing
        and n.roleName in TEXT_WIDGET_ROLES
        and (getattr(n, "focusable", False) or getattr(n, "editable", False))
    )
    assert areas, "Editable text area not found in GNOME Text Editor"
    return areas[0]


def _buffer_text(area=None) -> str:
    area = area or _editable_text_area()
    texts = []
    direct_text = _node_text(area)
    if direct_text:
        texts.append(direct_text)
    descendants = area.findChildren(
        lambda n: n.showing and n.roleName in TEXT_WIDGET_ROLES and bool(_node_text(n))
    )
    for node in descendants:
        text = _node_text(node)
        if text and text not in texts:
            texts.append(text)
    return "\n".join(texts).strip()


def _visible_dialog_text(dialog) -> list[str]:
    texts = []
    for node in dialog.findChildren(lambda n: n.showing and bool(_node_text(n))):
        text = _node_text(node)
        if text and text not in texts:
            texts.append(text)
    return texts


@step("Text Editor window has an editable text area")
def text_editor_window_has_editable_text_area(context) -> None:
    for _ in range(20):
        try:
            area = _editable_text_area()
            context.text_editor_window = _text_editor_window()
            context.text_editor_area = area
            context.text_editor_initial_buffer = _buffer_text(area)
            try:
                area.click()
            except Exception:  # noqa: BLE001
                pass
            return
        except Exception:  # noqa: BLE001
            sleep(0.5)
    raise AssertionError("Editable text area was not accessible in GNOME Text Editor")


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


@step("Text Editor is no longer running")
def text_editor_is_no_longer_running(context) -> None:
    for _ in range(20):
        for name in TEXT_EDITOR_APP_NAMES:
            try:
                app = _app_no_retry(name)
                if app is None:
                    continue
                frames = app.findChildren(lambda n: n.roleName in {"frame", "filler"} and n.showing)
                if frames:
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            return
        sleep(0.5)
    raise AssertionError("GNOME Text Editor is still visible in the AT-SPI tree")


@step('Text Editor buffer contains "{expected}"')
def text_editor_buffer_contains(context, expected: str) -> None:
    for _ in range(20):
        area = _editable_text_area()
        current_text = _buffer_text(area)
        if expected in current_text:
            context.text_editor_area = area
            context.text_editor_last_text = expected
            return
        sleep(0.5)
    raise AssertionError(
        f"Expected {expected!r} in Text Editor buffer, found {current_text!r}\n"
        f"Text Editor window tree:\n{_window_tree()}"
    )


@step("Text Editor creates a new empty document buffer")
def text_editor_creates_new_empty_document_buffer(context) -> None:
    previous_text = getattr(context, "text_editor_last_text", "").strip()
    for _ in range(20):
        area = _editable_text_area()
        current_text = _buffer_text(area)
        if not current_text.strip() and previous_text not in current_text:
            context.text_editor_area = area
            return
        sleep(0.5)
    raise AssertionError(
        f"Expected a new empty Text Editor buffer after Ctrl+N, found {current_text!r}\n"
        f"Text Editor window tree:\n{_window_tree()}"
    )


def _window_tree() -> str:
    """The focused window's subtree for a failure message; never raises."""
    try:
        return describe_subtree(_text_editor_window(), max_depth=6, max_lines=60)
    except Exception as exc:  # noqa: BLE001
        return f"(no window: {exc})"


def _visible_dialogs() -> list:
    """Text Editor's own dialogs (libadwaita alerts sit inside its window)."""
    return _text_editor_app().findChildren(lambda n: n.roleName in DIALOG_ROLES and n.showing)


def _file_chooser_hosts() -> list:
    """Apps that may own the file chooser: a portal backend, or Files.

    GNOME OS 51 shows Text Editor's "Save a File" chooser in a top-level
    window outside Text Editor, while Nautilus is registered.
    """
    hosts = []
    try:
        for app in tree.root.applications():
            name = (getattr(app, "name", "") or "").strip("'\" ").casefold()
            if "portal" in name or "nautilus" in name:
                hosts.append(app)
    except Exception:  # noqa: BLE001
        pass
    return hosts


def _has_save_button(window) -> bool:
    return any(
        (button.name or "").strip().casefold() == "save"
        for button in window.findChildren(lambda n: n.showing and n.roleName in BUTTON_ROLES)
    )


def _file_chooser_windows() -> list:
    """Showing file-chooser windows of other apps: only those with a "Save" button,
    so an ordinary Files window never counts."""
    windows = []
    for host in _file_chooser_hosts():
        for window in host.findChildren(lambda n: n.roleName in PORTAL_WINDOW_ROLES and n.showing):
            if _has_save_button(window):
                windows.append(window)
    return windows


def _dialog_debug() -> str:
    apps = []
    try:
        apps = [getattr(app, "name", "") for app in tree.root.applications()]
    except Exception:  # noqa: BLE001
        pass
    try:
        dialogs = [_visible_dialog_text(d) for d in _visible_dialogs()]
    except Exception as exc:  # noqa: BLE001
        dialogs = [f"(lookup failed: {exc})"]
    hosts = []
    try:
        for host in _file_chooser_hosts():
            hosts.append(describe_subtree(host, max_depth=2, max_lines=20))
    except Exception as exc:  # noqa: BLE001
        hosts.append(f"(lookup failed: {exc})")
    return (
        f"Visible dialogs: {dialogs}\nApplications: {apps}\n"
        f"File-chooser hosts:\n" + "\n".join(hosts) + "\n"
        f"Text Editor window tree:\n{_window_tree()}"
    )


@step("Text Editor save dialog is open")
def text_editor_save_dialog_is_open(context) -> None:
    for _ in range(20):
        for dialog in _visible_dialogs():
            entries = dialog.findChildren(
                lambda n: n.showing and n.roleName in DIALOG_ENTRY_ROLES
            )
            buttons = dialog.findChildren(
                lambda n: n.showing and n.roleName in BUTTON_ROLES
            )
            if entries or any("save" in (button.name or "").casefold() for button in buttons):
                context.text_editor_save_dialog = dialog
                return
        choosers = _file_chooser_windows()
        if choosers:
            context.text_editor_save_dialog = choosers[0]
            return
        sleep(0.5)
    raise AssertionError(f"Text Editor save dialog was not found. {_dialog_debug()}")


@step("Text Editor discard dialog is open")
def text_editor_discard_dialog_is_open(context) -> None:
    """Assert that the 'unsaved changes' dialog is shown with a Discard button."""
    for _ in range(20):
        for dialog in _visible_dialogs():
            buttons = dialog.findChildren(
                lambda n: n.showing and n.roleName in BUTTON_ROLES
            )
            if any("discard" in (b.name or "").casefold() for b in buttons):
                context.text_editor_discard_dialog = dialog
                return
        sleep(0.5)
    raise AssertionError(
        f"Text Editor discard dialog (with Discard button) not found. {_dialog_debug()}"
    )
