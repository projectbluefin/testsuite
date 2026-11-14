"""Custom step definitions for GNOME Calculator smoke tests."""
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
    node_text,
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


CALCULATOR_APP_NAMES = ("gnome-calculator", "Calculator")
CALCULATOR_LAUNCH_TARGETS = (
    ("command", "gnome-calculator"),
    ("desktop", "org.gnome.Calculator.desktop"),
)
BUTTON_ROLES = {"push button", "button"}
DISPLAY_ROLES = {"text", "entry", "label", "static"}
BUTTON_ALIASES = {
    "+": {"+", "plus", "＋"},
    "-": {"-", "−", "minus", "subtract", "–"},
    "×": {"×", "*", "multiply", "⊗"},
    "÷": {"÷", "/", "divide"},
    ".": {".", "decimal point", "decimal", "point"},
    "=": {"=", "equals"},
    "clear": {"c", "clear", "ac", "all clear"},
}


def _calculator_app():
    """Take one ``applications()`` snapshot; dogtail's per-name lookup retries internally."""
    last_error = None
    try:
        for app in tree.root.applications():
            if (getattr(app, "name", "") or "").strip("'\" ") in CALCULATOR_APP_NAMES:
                return app
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    raise AssertionError(
        f"GNOME Calculator application was not found via AT-SPI: "
        f"{last_error or f'none of {CALCULATOR_APP_NAMES} registered'}"
    )


@step("Launch Calculator via command")
def launch_calculator_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    # Each launch of the running app opens another window; start from none.
    stop_app_instances("gnome-calculator")
    context.calculator_launch_target = launch_background(CALCULATOR_LAUNCH_TARGETS)


def _calculator_window():
    app = _calculator_app()
    frames = app.findChildren(lambda n: n.roleName in {"frame", "filler"} and n.showing)
    assert frames, "Visible GNOME Calculator window not found"
    return newest_active_frame(frames)


def _normalize(text: str) -> str:
    return (text or "").strip().casefold().replace("−", "-").replace("–", "-")


def _button_targets(name: str) -> set[str]:
    normalized = _normalize(name)
    aliases = BUTTON_ALIASES.get(normalized, {normalized})
    return {_normalize(alias) for alias in aliases}


def _inside_button(node) -> bool:
    """True when a node sits under a keypad or menu button (its label, not the display)."""
    parent = getattr(node, "parent", None)
    for _ in range(12):
        if parent is None:
            return False
        role = getattr(parent, "roleName", "")
        if isinstance(role, str) and "button" in role:
            return True
        if role == "frame":
            return False
        parent = getattr(parent, "parent", None)
    return False


def _display_candidates(window=None):
    window = window or _calculator_window()
    candidates = []
    for node in window.findChildren(
        lambda n: n.showing and n.roleName in DISPLAY_ROLES and not _inside_button(n)
    ):
        name = (getattr(node, "name", "") or "").strip()
        value = node_text(node) or name
        if value:
            candidates.append(value)
    return candidates


def _calculator_button(name: str):
    targets = _button_targets(name)
    window = _calculator_window()
    buttons = window.findChildren(
        lambda n: n.showing and n.roleName in BUTTON_ROLES and bool((n.name or "").strip())
    )
    for button in buttons:
        if _normalize(button.name) in targets:
            return button
    raise AssertionError(
        f"Calculator button {name!r} not found. Visible buttons: {[button.name for button in buttons]}"
    )


@step("Calculator window is accessible")
def calculator_window_is_accessible(context) -> None:
    for _ in range(20):
        try:
            context.calculator_window = _calculator_window()
            if _calculator_button("1"):
                return
        except Exception:  # noqa: BLE001
            sleep(0.5)
    raise AssertionError("GNOME Calculator window was not accessible")


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


@step("Calculator is no longer running")
def calculator_is_no_longer_running(context) -> None:
    for _ in range(20):
        for name in CALCULATOR_APP_NAMES:
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
    raise AssertionError("GNOME Calculator is still visible in the AT-SPI tree")


@step('Click calculator button "{name}"')
def click_calculator_button(context, name: str) -> None:
    button = _calculator_button(name)
    button.click()
    context.last_calculator_button = name
    sleep(0.1)


@step('Calculator display shows "{expected}"')
def calculator_display_shows(context, expected: str) -> None:
    normalized_expected = _normalize(expected)
    last_candidates = []
    window = None
    for _ in range(20):
        window = _calculator_window()
        last_candidates = _display_candidates(window)
        normalized_candidates = [_normalize(candidate) for candidate in last_candidates]
        if any(
            candidate == normalized_expected or candidate.endswith(normalized_expected)
            for candidate in normalized_candidates
        ):
            context.calculator_display = last_candidates
            return
        sleep(0.5)
    raise AssertionError(
        f"Expected calculator display to show {expected!r}, found {last_candidates!r}\n"
        f"Calculator window tree:\n{describe_subtree(window) if window is not None else '(none)'}"
    )


DISPLAY_FIELD_ROLES = {"text", "entry"}


@step("Calculator display is cleared")
def calculator_display_is_cleared(context) -> None:
    """The input field is empty or 0: GNOME 51 clears to an empty field, older
    releases to 0. History labels are not the input field and are ignored."""
    values = []
    window = None
    for _ in range(20):
        window = _calculator_window()
        fields = window.findChildren(
            lambda n: n.showing and n.roleName in DISPLAY_FIELD_ROLES and not _inside_button(n)
        )
        values = [node_text(field) or (getattr(field, "name", "") or "").strip() for field in fields]
        if fields and all(value in {"", "0"} for value in values):
            return
        sleep(0.5)
    raise AssertionError(
        f"Expected the calculator input field to be empty or 0, found {values!r}\n"
        f"Calculator window tree:\n{describe_subtree(window) if window is not None else '(none)'}"
    )


@step("Clear calculator display")
def clear_calculator_display(context) -> None:
    for candidate in ("clear", "C", "AC"):
        try:
            _calculator_button(candidate).click()
            sleep(0.1)
            return
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("Calculator clear button was not found")
