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
from app_support import launch_background


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


def _text_editor_app():
    last_error = None
    for name in TEXT_EDITOR_APP_NAMES:
        try:
            return tree.root.application(name)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise AssertionError(
        f"GNOME Text Editor application was not found via AT-SPI: {last_error}"
    )


@step("Launch Text Editor via command")
def launch_text_editor_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.text_editor_launch_target = launch_background(TEXT_EDITOR_LAUNCH_TARGETS)


def _text_editor_window():
    app = _text_editor_app()
    frames = app.findChildren(lambda n: n.roleName in {"frame", "filler"} and n.showing)
    assert frames, "Visible GNOME Text Editor window not found"
    return frames[0]


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
    raise AssertionError(f"Expected {expected!r} in Text Editor buffer, found {current_text!r}")


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
        f"Expected a new empty Text Editor buffer after Ctrl+N, found {current_text!r}"
    )


@step("Text Editor save dialog is open")
def text_editor_save_dialog_is_open(context) -> None:
    app = _text_editor_app()
    for _ in range(20):
        dialogs = app.findChildren(lambda n: n.roleName == "dialog" and n.showing)
        for dialog in dialogs:
            entries = dialog.findChildren(
                lambda n: n.showing and n.roleName in DIALOG_ENTRY_ROLES
            )
            buttons = dialog.findChildren(
                lambda n: n.showing and n.roleName in BUTTON_ROLES
            )
            if entries or any("save" in (button.name or "").casefold() for button in buttons):
                context.text_editor_save_dialog = dialog
                return
        sleep(0.5)
    dialog_debug = []
    dialogs = app.findChildren(lambda n: n.roleName == "dialog" and n.showing)
    for dialog in dialogs:
        dialog_debug.append(_visible_dialog_text(dialog))
    raise AssertionError(f"Text Editor save dialog was not found. Visible dialogs: {dialog_debug}")


@step("Text Editor discard dialog is open")
def text_editor_discard_dialog_is_open(context) -> None:
    """Assert that the 'unsaved changes' dialog is shown with a Discard button."""
    app = _text_editor_app()
    for _ in range(20):
        dialogs = app.findChildren(lambda n: n.roleName == "dialog" and n.showing)
        for dialog in dialogs:
            buttons = dialog.findChildren(
                lambda n: n.showing and n.roleName in BUTTON_ROLES
            )
            if any("discard" in (b.name or "").casefold() for b in buttons):
                context.text_editor_discard_dialog = dialog
                return
        sleep(0.5)
    dialog_debug = [_visible_dialog_text(d) for d in
                    app.findChildren(lambda n: n.roleName == "dialog" and n.showing)]
    raise AssertionError(
        f"Text Editor discard dialog (with Discard button) not found. "
        f"Visible dialogs: {dialog_debug}"
    )
    app = _text_editor_app()
    for _ in range(20):
        dialogs = app.findChildren(lambda n: n.roleName == "dialog" and n.showing)
        for dialog in dialogs:
            entries = dialog.findChildren(
                lambda n: n.showing and n.roleName in DIALOG_ENTRY_ROLES
            )
            buttons = dialog.findChildren(
                lambda n: n.showing and n.roleName in BUTTON_ROLES
            )
            if entries or any("save" in (button.name or "").casefold() for button in buttons):
                context.text_editor_save_dialog = dialog
                return
        sleep(0.5)
    dialog_debug = []
    dialogs = app.findChildren(lambda n: n.roleName == "dialog" and n.showing)
    for dialog in dialogs:
        dialog_debug.append(_visible_dialog_text(dialog))
    raise AssertionError(f"Text Editor save dialog was not found. Visible dialogs: {dialog_debug}")
