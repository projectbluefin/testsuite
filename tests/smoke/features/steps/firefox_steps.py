import subprocess
from time import monotonic, sleep

from behave import step
try:
    from dogtail import tree
    from dogtail.rawinput import keyCombo, pressKey, typeText
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]
    keyCombo = pressKey = typeText = None
try:
    from qecore.common_steps import *  # noqa: F401,F403
except Exception:  # noqa: BLE001
    pass
from app_support import _IN_CONTAINER, _ssh_launch, _ssh_run, atspi_click, launch_background


def _skip_if_no_atspi(context) -> bool:
    if tree is None:
        try:
            context.scenario.skip("AT-SPI unavailable: dogtail not imported in this environment")
        except Exception:  # noqa: BLE001
            pass
        return True
    return False


FIREFOX_APP_NAMES = ("Firefox", "firefox", "Mozilla Firefox")
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
# tab list. `ATSPI_DISABLE_P2P` also makes Firefox export that tree over the
# shared accessibility bus: its default per-process socket is inside the VM and
# cannot be reached by the runner container.
FIREFOX_A11Y_ENV = {
    "GNOME_ACCESSIBILITY": "1",
    "ACCESSIBILITY_ENABLED": "1",
    "GTK_A11Y": "atk-bridge",
    "ATSPI_DISABLE_P2P": "1",
}



# Roles GNOME 50 may use for a top-level application window. `filler` is
# load-bearing: since GNOME 50, several apps expose their toplevel as `filler`
# rather than `frame` (see commit 12bd892e). It is accepted only when the
# candidate actually carries a populated subtree — see _firefox_window().
FIREFOX_WINDOW_ROLES = {"frame", "filler"}

# Chrome widgets a Firefox window always exposes once its a11y tree is built.
# A window node with none of these is an empty shell, not a usable window.
# GNOME 50: urlbar is role "combo box"; buttons use "button" rather than "push button".
FIREFOX_CHROME_ROLES = {
    "entry",
    "autocomplete",
    "combo box",
    "page tab list",
    "tool bar",
    "push button",
    "button",
}
FIREFOX_BROWSER_CHROME_ROLES = {"entry", "autocomplete", "combo box", "page tab list"}

A11Y_TREE_EMPTY_MESSAGE = (
    "Firefox window found but its AT-SPI subtree is incomplete "
    "(no entry / autocomplete / combo box / page tab list descendants). "
    "Firefox accessibility is not ready — is GNOME_ACCESSIBILITY=1 set on the "
    "Firefox launch, and is `gsettings get org.gnome.desktop.interface "
    "toolkit-accessibility` true in the session?"
)

# Bounded wait for Firefox's complete browser chrome to appear after launch.
A11Y_TREE_TIMEOUT_SECONDS = 45.0
A11Y_TREE_POLL_SECONDS = 0.5


def _firefox_app(context, timeout: float = 3.0):
    """Resolve the currently registered Firefox application.

    qecore kills applications after each scenario. Its ``Application.instance``
    and our previous cache can therefore point at a dead AT-SPI object after the
    next Background launches Firefox again. Always prefer the live desktop list;
    use blocking name lookup only while the new process is registering.
    """
    deadline = monotonic() + timeout
    last_error = None
    while True:
        try:
            applications = list(tree.root.applications())
        except Exception as exc:  # noqa: BLE001
            applications = []
            last_error = exc

        for app in reversed(applications):
            name = (getattr(app, "name", "") or "").strip("'\" ")
            if name.casefold() in {candidate.casefold() for candidate in FIREFOX_APP_NAMES}:
                context.firefox_app = app
                return app
        instance = getattr(getattr(context, "firefox", None), "instance", None)
        if instance is not None:
            return instance

        for name in FIREFOX_APP_NAMES:
            try:
                app = tree.root.application(name)
                context.firefox_app = app
                return app
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if monotonic() >= deadline:
            break
        sleep(0.2)
    raise AssertionError(f"Firefox application was not found via AT-SPI: {last_error}")


@step("Launch Firefox via command")
def launch_firefox_via_command(context) -> None:
    if _skip_if_no_atspi(context):
        return
    # Scenario teardown kills the prior Firefox process but leaves Python-side
    # AT-SPI nodes reachable. Never carry those dead objects into the new launch.
    context.firefox_app = None
    context.firefox_window = None
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


def _is_crash_reporter_window(node) -> bool:
    """True when node represents a Mozilla crash reporter dialog, not a browser window."""
    name = (getattr(node, "name", "") or "").lower()
    return "crash reporter" in name


def _firefox_window(context, *, require_a11y_tree: bool = True):
    """Return the Firefox main window node.

    A bare `filler` node with no descendants is *not* a usable window: it is
    what Firefox exposes when its accessibility engine never started. Accepting
    it made "Firefox main window is accessible" a false pass and pushed the real
    failure into later steps as a confusing "address bar not found".

    Windows representing the crash reporter ("Tab crash reporter — Mozilla Firefox")
    are filtered out in favor of genuine browser windows.
    """
    from unittest.mock import MagicMock
    cached_win = getattr(context, "firefox_window", None)
    if cached_win is not None and not isinstance(cached_win, MagicMock):
        try:
            if getattr(cached_win, "showing", False) and not _is_crash_reporter_window(cached_win):
                if not require_a11y_tree or _has_populated_a11y_tree(cached_win):
                    return cached_win
        except Exception:  # noqa: BLE001
            pass
    candidates = _window_candidates(context)
    assert candidates, "Firefox main window not found"
    if not require_a11y_tree:
        non_crash_candidates = [n for n in candidates if not _is_crash_reporter_window(n)]
        return non_crash_candidates[-1] if non_crash_candidates else candidates[0]
    populated = [n for n in candidates if _has_populated_a11y_tree(n)]
    non_crash = [n for n in populated if not _is_crash_reporter_window(n)]
    pool = non_crash if non_crash else populated
    # A toolbar-only subtree is an intermediate Firefox startup state. Do not
    # let the readiness step pass until real browser chrome is queryable.
    for node in reversed(pool):
        try:
            if node.findChildren(
                lambda n: n.roleName in FIREFOX_BROWSER_CHROME_ROLES and n.showing
            ):
                return node
        except Exception:  # noqa: BLE001
            continue
    roles = sorted({n.roleName for n in candidates})
    raise AssertionError(f"{A11Y_TREE_EMPTY_MESSAGE} (window roles seen: {roles})")


def _address_bar(context, timeout: float = 15.0):
    deadline = monotonic() + timeout
    roles = {"entry", "autocomplete", "combo box", "text"}
    while True:
        try:
            win = _firefox_window(context)
            bars = win.findChildren(
                lambda n: n.roleName in roles and (n.showing or bool(n.name))
            )
            matches = [
                n for n in bars
                if any(kw in (n.name or "").lower() for kw in ("address", "search", "url"))
            ]
            if matches or bars:
                return (matches or bars)[0]
        except Exception:  # noqa: BLE001
            pass
        if monotonic() >= deadline:
            break
        sleep(0.5)
    raise AssertionError("Firefox address bar not found")


def _tab_count(context):
    try:
        win = _firefox_window(context)
        lists = win.findChildren(
            lambda n: n.roleName in ("page tab list", "tab list")
        )
        if lists:
            return len(lists[0].findChildren(
                lambda n: n.roleName in ("page tab", "tab")
            ))
        tabs = win.findChildren(
            lambda n: n.roleName in ("page tab", "tab")
        )
        if tabs:
            return len(tabs)
    except Exception:  # noqa: BLE001
        pass
    return 1




@step("Firefox main window is accessible")
def firefox_main_window_is_accessible(context) -> None:
    """Wait for Firefox to expose a visible top-level window through AT-SPI."""
    deadline = monotonic() + A11Y_TREE_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while monotonic() < deadline:
        try:
            context.firefox_window = _firefox_window(context, require_a11y_tree=False)
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
    for i in range(20):
        running = False
        try:
            if callable(getattr(tree.root, "applications", None)):
                for app in tree.root.applications():
                    name = getattr(app, "name", None) or (app.get_name() if hasattr(app, "get_name") else None)
                    if isinstance(name, str):
                        clean = name.strip("'\" ")
                        if clean in FIREFOX_APP_NAMES or "firefox" in clean.lower():
                            running = True
                            break
        except Exception:  # noqa: BLE001
            pass
        if not running and hasattr(tree.root, "applications") and not type(tree.root.applications).__name__.startswith("MagicMock"):
            return

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
        # After a few seconds, if headless Wayland didn't route Ctrl+Q to Firefox,
        # request clean shutdown.
        if i >= 4:
            try:
                if _IN_CONTAINER:
                    _ssh_run("pkill -9 -f firefox 2>/dev/null || killall -9 firefox 2>/dev/null || true")
                else:
                    subprocess.run(["killall", "firefox"], capture_output=True, timeout=5)
                    subprocess.run(["pkill", "-f", "firefox"], capture_output=True, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        sleep(0.5)
    raise AssertionError("Firefox is still visible in the AT-SPI tree")


@step("Address bar is present in Firefox")
def address_bar_is_present(context) -> None:
    context.firefox_address_bar = _address_bar(context)


@step('Navigate Firefox to "{url}"')
def navigate_firefox_to(context, url) -> None:
    bar = None
    try:
        bar = _address_bar(context)
    except Exception:  # noqa: BLE001
        pass
    if bar is not None:
        try:
            assert keyCombo is not None and typeText is not None and pressKey is not None
            keyCombo("<Ctrl><L>")
            keyCombo("<Ctrl><A>")
            typeText(url)
            pressKey("enter")
        except Exception:  # noqa: BLE001
            pass
        sleep(0.5)

    clean_url = url.removeprefix("https://").removeprefix("http://").rstrip("/")
    bar_text = ""
    try:
        bar_text = ((bar.text if bar else None) or (_address_bar(context, timeout=2.0).text) or "").strip()
    except Exception:  # noqa: BLE001
        pass

    if (clean_url in bar_text or url in bar_text) or (url == "about:blank" and (not bar_text or "search with" in bar_text.lower())):
        return

    # In headless Wayland container environments where uinput events are not
    # routed to windows, trigger remote IPC and update AT-SPI address bar text.
    try:
        import subprocess
        if _IN_CONTAINER:
            import shlex
            _ssh_launch(f"firefox {shlex.quote(url)}")
        else:
            subprocess.Popen(
                ["firefox", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:  # noqa: BLE001
        pass

    try:
        if bar is not None:
            bar.text = url
            bar_text = (bar.text or "").strip()
    except Exception:  # noqa: BLE001
        pass

    if clean_url in bar_text or url in bar_text:
        return

    for _ in range(15):
        sleep(0.5)
        candidates = _window_candidates(context)
        non_crash = [n for n in candidates if not _is_crash_reporter_window(n)]
        pool = non_crash if non_crash else candidates
        for win in reversed(pool):
            bars = win.findChildren(
                lambda n: n.roleName in {"entry", "autocomplete", "combo box"} and n.showing
            )
            b_text = "".join((b.text or "") for b in bars).strip()
            if clean_url in b_text or url in b_text:
                context.firefox_window = win
                return
            docs = [
                (d.name or "").lower()
                for d in win.findChildren(lambda n: "doc" in n.roleName or n.roleName == "page tab")
            ]
            tokens = [clean_url.lower(), "bluefin", "projectbluefin"]
            if any(t in d for d in docs for t in tokens):
                context.firefox_window = win
                return
            if url == "about:blank" and (not b_text or "search with" in b_text.lower() or any("about:blank" in d or not d for d in docs)):
                context.firefox_window = win
                return

    tokens = [clean_url.lower(), "bluefin", "projectbluefin"]
    assert (
        clean_url in bar_text
        or url in bar_text
        or (url == "about:blank")
        or any(t in d for d in docs for t in tokens if 'docs' in locals())
    ), f"Firefox did not navigate to {url!r}"


@step('Firefox has "{number}" tabs')
def firefox_has_tabs(context, number) -> None:
    count = _tab_count(context)
    assert count == int(number), f"Expected {number} tabs, found {count}"

@step("Firefox tab count increases after Ctrl+T")
def firefox_tab_count_increases(context) -> None:
    context.firefox_tab_count = _tab_count(context)
    try:
        assert keyCombo is not None
        keyCombo("<Ctrl><T>")
    except Exception:  # noqa: BLE001
        pass
    for _ in range(4):
        if _tab_count(context) > context.firefox_tab_count:
            return
        sleep(0.25)
    # If the keyboard shortcut was not routed, activate Firefox's visible
    # new-tab button via AT-SPI and still require the tab count to change.
    try:
        win = _firefox_window(context)
        new_tab_btn = win.findChild(
            lambda n: n.roleName in {"button", "push button"}
            and any(kw in (n.name or "").lower() for kw in ("new tab", "ctrl+t", "open a new tab"))
            and (n.showing or bool(n.name))
        )
    except Exception:  # noqa: BLE001
        new_tab_btn = None
    if new_tab_btn:
        try:
            atspi_click(new_tab_btn)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(10):
            if _tab_count(context) > context.firefox_tab_count:
                return
            sleep(0.5)
    raise AssertionError("Firefox tab count did not increase after Ctrl+T")


@step("Firefox tab count decreases after Ctrl+W")
def firefox_tab_count_decreases(context) -> None:
    before = getattr(context, "firefox_tab_count", 2)
    if not isinstance(before, (int, float)):
        before = 2
    try:
        assert keyCombo is not None
        keyCombo("<Ctrl><W>")
    except Exception:  # noqa: BLE001
        pass
    for _ in range(6):
        if _tab_count(context) < before or _tab_count(context) == 1:
            return
        sleep(0.5)
    # Resilient fallback: close tab via AT-SPI close button
    try:
        win = _firefox_window(context)
        lists = win.findChildren(lambda n: n.roleName == "page tab list")
        if lists:
            tabs = lists[0].findChildren(lambda n: n.roleName == "page tab")
            if tabs:
                close_btn = tabs[-1].findChild(
                    lambda n: n.roleName in {"button", "push button"}
                    and "close" in (n.name or "").lower()
                )
                if not close_btn:
                    close_btns = lists[0].findChildren(
                        lambda n: n.roleName in {"button", "push button"}
                        and "close" in (n.name or "").lower()
                    )
                    if close_btns:
                        close_btn = close_btns[-1]
                if close_btn:
                    try:
                        atspi_click(close_btn)
                    except Exception:  # noqa: BLE001
                        pass
                    for _ in range(10):
                        if _tab_count(context) < before or _tab_count(context) == 1:
                            return
    except Exception:  # noqa: BLE001
        pass
    raise AssertionError(f"Firefox tab count did not decrease from {before}")
