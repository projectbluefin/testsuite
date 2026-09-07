from time import monotonic, sleep

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


FIREFOX_APP_NAMES = ("firefox", "Firefox", "Mozilla Firefox")
FIREFOX_LAUNCH_TARGETS = (
    ("command", "firefox"),
    ("desktop", "firefox.desktop"),
    ("flatpak", "org.mozilla.firefox"),
    ("desktop", "org.mozilla.firefox.desktop"),
)

# Firefox does not build its accessibility tree just because the session has
# `org.gnome.desktop.interface toolkit-accessibility` enabled — that setting
# only drives the GTK atk-bridge, and Firefox renders its own chrome. Firefox
# gates its AT-SPI bridge on these environment variables at process start, so
# they must be present in the launched process's environment. Without them the
# app registers with AT-SPI but exposes an empty subtree: no address bar, no
# tab list. Mirrors the launch env already used in gnome_extensions_steps.py.
FIREFOX_A11Y_ENV = {
    "GNOME_ACCESSIBILITY": "1",
    "ACCESSIBILITY_ENABLED": "1",
    "GTK_A11Y": "atk-bridge",
}

# Roles GNOME 50 may use for a top-level application window. `filler` is
# load-bearing: since GNOME 50, several apps expose their toplevel as `filler`
# rather than `frame` (see commit 12bd892e). It is accepted only when the
# candidate actually carries a populated subtree — see _firefox_window().
FIREFOX_WINDOW_ROLES = {"frame", "filler"}

# Chrome widgets a Firefox window always exposes once its a11y tree is built.
# A window node with none of these is an empty shell, not a usable window.
FIREFOX_CHROME_ROLES = {"entry", "page tab list", "tool bar", "push button"}

A11Y_TREE_EMPTY_MESSAGE = (
    "Firefox window found but its AT-SPI subtree is empty "
    "(no entry / tool bar / page tab list descendants). "
    "Firefox accessibility is not enabled — is GNOME_ACCESSIBILITY=1 set on the "
    "Firefox launch, and is `gsettings get org.gnome.desktop.interface "
    "toolkit-accessibility` true in the session?"
)

# Bounded wait for Firefox's a11y tree to appear after launch.
A11Y_TREE_TIMEOUT_SECONDS = 30.0
A11Y_TREE_POLL_SECONDS = 0.5


def _firefox_app(context):
    instance = getattr(getattr(context, "firefox", None), "instance", None)
    if instance is not None:
        return instance
    last_error = None
    for name in FIREFOX_APP_NAMES:
        try:
            return tree.root.application(name)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise AssertionError(f"Firefox application was not found via AT-SPI: {last_error}")


@step("Launch Firefox via command")
def launch_firefox_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    context.firefox_launch_target = launch_background(
        FIREFOX_LAUNCH_TARGETS, env=FIREFOX_A11Y_ENV
    )


def _window_candidates(context):
    app = _firefox_app(context)
    top_level = [
        c for c in getattr(app, "children", [])
        if c.roleName in FIREFOX_WINDOW_ROLES and c.showing
    ]
    if top_level:
        return top_level
    return app.findChildren(
        lambda n: n.roleName in FIREFOX_WINDOW_ROLES and n.showing
    )


def _has_populated_a11y_tree(node) -> bool:
    """True when ``node`` exposes real Firefox chrome widgets via AT-SPI."""
    try:
        return bool(node.findChildren(lambda n: n.roleName in FIREFOX_CHROME_ROLES))
    except Exception:  # noqa: BLE001
        return False


def _firefox_window(context, *, require_a11y_tree: bool = True):
    """Return the Firefox main window node.

    A bare `filler` node with no descendants is *not* a usable window: it is
    what Firefox exposes when its accessibility engine never started. Accepting
    it made "Firefox main window is accessible" a false pass and pushed the real
    failure into later steps as a confusing "address bar not found".
    """
    candidates = _window_candidates(context)
    assert candidates, "Firefox main window not found"
    if not require_a11y_tree:
        return candidates[0]
    # Prefer a real `frame`; fall back to any candidate with a usable subtree.
    populated = [n for n in candidates if _has_populated_a11y_tree(n)]
    # Prefer a frame with browser chrome (entry, autocomplete, or tab list)
    for node in populated:
        try:
            if node.roleName == "frame" and node.findChildren(
                lambda n: n.roleName in {"entry", "autocomplete", "page tab list"} and n.showing
            ):
                return node
        except Exception:  # noqa: BLE001
            pass
    # Fall back to any candidate with browser chrome (e.g. GNOME 50 filler window)
    for node in populated:
        try:
            if node.findChildren(
                lambda n: n.roleName in {"entry", "autocomplete", "page tab list"} and n.showing
            ):
                return node
        except Exception:  # noqa: BLE001
            pass
    # Fall back to any populated frame
    for node in populated:
        if node.roleName == "frame":
            return node
    if populated:
        return populated[0]
    roles = sorted({n.roleName for n in candidates})
    raise AssertionError(f"{A11Y_TREE_EMPTY_MESSAGE} (window roles seen: {roles})")


def _address_bar(context):
    bars = _firefox_window(context).findChildren(
        lambda n: n.roleName in {"entry", "autocomplete"} and n.showing
    )
    matches = [
        n for n in bars
        if any(kw in (n.name or "").lower() for kw in ("address", "search", "url"))
    ]
    assert matches or bars, "Firefox address bar not found"
    return (matches or bars)[0]


def _tab_count(context):
    lists = _firefox_window(context).findChildren(lambda n: n.roleName == "page tab list" and n.showing)
    assert lists, "Firefox tab list not found"
    return len(lists[0].findChildren(lambda n: n.roleName == "page tab"))


@step("Firefox main window is accessible")
def firefox_main_window_is_accessible(context) -> None:
    """Wait, bounded, for a Firefox window with a populated AT-SPI subtree.

    Firefox builds its accessibility tree lazily after the window maps, so a
    poll is required; the deadline is explicit rather than a bare sleep.
    """
    deadline = monotonic() + A11Y_TREE_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while monotonic() < deadline:
        try:
            context.firefox_window = _firefox_window(context)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            sleep(A11Y_TREE_POLL_SECONDS)
    raise AssertionError(
        f"Firefox main window not accessible after "
        f"{A11Y_TREE_TIMEOUT_SECONDS:.0f}s: {last_error}"
    )


@step("Firefox is no longer running")
def firefox_is_no_longer_running(context) -> None:
    for _ in range(20):
        for name in FIREFOX_APP_NAMES:
            try:
                app = tree.root.application(name)
                # Liveness check only — an empty-subtree window still counts as
                # "Firefox is running", so do not require an a11y tree here.
                frames = app.findChildren(
                    lambda n: n.roleName in FIREFOX_WINDOW_ROLES and n.showing
                )
                if frames:
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            return
        sleep(0.5)
    raise AssertionError("Firefox is still visible in the AT-SPI tree")


@step("Address bar is present in Firefox")
def address_bar_is_present(context) -> None:
    context.firefox_address_bar = _address_bar(context)
    context.firefox_address_bar.click()


@step('Navigate Firefox to "{url}"')
def navigate_firefox_to(context, url) -> None:
    _address_bar(context).click()
    context.execute_steps(f'''* Key combo: "<Ctrl><A>" with uinput
* Type text: "{url}" with uinput
* Press key: "Return" with uinput''')
    sleep(0.3)
    assert url in (_address_bar(context).text or ""), f"Firefox did not navigate to {url!r}"


@step('Firefox has "{number}" tabs')
def firefox_has_tabs(context, number) -> None:
    count = _tab_count(context)
    assert count == int(number), f"Expected {number} tabs, found {count}"


@step("Firefox tab count increases after Ctrl+T")
def firefox_tab_count_increases(context) -> None:
    context.firefox_tab_count = _tab_count(context)
    context.execute_steps('* Key combo: "<Ctrl><T>" with uinput')
    for _ in range(10):
        if _tab_count(context) > context.firefox_tab_count:
            return
        sleep(0.5)
    raise AssertionError("Firefox tab count did not increase after Ctrl+T")


@step("Firefox tab count decreases after Ctrl+W")
def firefox_tab_count_decreases(context) -> None:
    before = _tab_count(context)
    context.execute_steps('* Key combo: "<Ctrl><W>" with uinput')
    for _ in range(10):
        if _tab_count(context) < before:
            return
        sleep(0.5)
    raise AssertionError("Firefox tab count did not decrease after Ctrl+W")
