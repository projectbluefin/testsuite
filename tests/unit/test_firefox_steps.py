"""Unit tests for firefox_steps.py pure helper functions."""
import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_firefox_steps(tree_available: bool = True):
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    if tree_available:
        tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    rawinput_stub = types.ModuleType("dogtail.rawinput")
    rawinput_stub.keyCombo = MagicMock()
    rawinput_stub.pressKey = MagicMock()
    rawinput_stub.typeText = MagicMock()
    sys.modules["dogtail.tree"] = tree_stub
    sys.modules["dogtail.rawinput"] = rawinput_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    app_support_stub = types.ModuleType("app_support")
    app_support_stub.launch_background = MagicMock()
    app_support_stub.atspi_click = MagicMock()
    app_support_stub._IN_CONTAINER = False
    app_support_stub._ssh_launch = MagicMock()
    app_support_stub._ssh_run = MagicMock()
    sys.modules["app_support"] = app_support_stub

    for key in list(sys.modules):
        if "firefox_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.firefox_steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestFirefoxConstants:
    def test_app_names_is_tuple(self):
        m = _import_firefox_steps()
        assert isinstance(m.FIREFOX_APP_NAMES, tuple)
        assert "firefox" in m.FIREFOX_APP_NAMES

    def test_app_names_has_mozilla_variant(self):
        m = _import_firefox_steps()
        assert any("Mozilla" in name or "firefox" in name.lower() for name in m.FIREFOX_APP_NAMES)

    def test_launch_targets_is_tuple(self):
        m = _import_firefox_steps()
        assert isinstance(m.FIREFOX_LAUNCH_TARGETS, tuple)
        assert len(m.FIREFOX_LAUNCH_TARGETS) >= 2

    def test_launch_targets_has_command_entry(self):
        m = _import_firefox_steps()
        types_ = [t for t, _ in m.FIREFOX_LAUNCH_TARGETS]
        assert "command" in types_

    def test_launch_targets_has_desktop_entry(self):
        m = _import_firefox_steps()
        types_ = [t for t, _ in m.FIREFOX_LAUNCH_TARGETS]
        assert "desktop" in types_


# ---------------------------------------------------------------------------
# _skip_if_no_atspi
# ---------------------------------------------------------------------------

class TestSkipIfNoAtspi:
    def test_returns_false_when_tree_available(self):
        m = _import_firefox_steps(tree_available=True)
        assert m._skip_if_no_atspi(MagicMock()) is False

    def test_returns_true_when_tree_is_none(self):
        m = _import_firefox_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        assert m._skip_if_no_atspi(context) is True

    def test_calls_scenario_skip_with_atspi_message(self):
        m = _import_firefox_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        context.scenario.skip.assert_called_once()
        assert "AT-SPI" in context.scenario.skip.call_args[0][0]

    def test_tolerates_skip_exception(self):
        m = _import_firefox_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        context.scenario.skip.side_effect = RuntimeError("no scenario")
        assert m._skip_if_no_atspi(context) is True


class TestFirefoxApp:
    def test_prefers_live_tree_application_over_stale_context_instance(self):
        m = _import_firefox_steps()
        stale = MagicMock()
        live = MagicMock()
        live.name = "Firefox"
        context = MagicMock()
        context.firefox.instance = stale
        context.firefox_app = stale
        m.tree.root.applications = MagicMock(return_value=[live])

        assert m._firefox_app(context) is live

    def test_fallback_when_live_application_list_is_empty(self):
        m = _import_firefox_steps()
        context = MagicMock(spec=[])
        found_app = MagicMock()
        m.tree.root.applications = MagicMock(return_value=[])
        m.tree.root.application = MagicMock(return_value=found_app)
        result = m._firefox_app(context)
        assert result is found_app

    def test_fallback_when_firefox_attr_missing(self):
        m = _import_firefox_steps()
        context = MagicMock(spec=[])  # no attributes
        found_app = MagicMock()
        m.tree.root.application = MagicMock(return_value=found_app)
        result = m._firefox_app(context)
        assert result is found_app

    def test_prefers_capitalized_firefox_app_name(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_APP_NAMES[0] == "Firefox"


    def test_retries_transient_failure(self):
        m = _import_firefox_steps()
        context = MagicMock()
        context.firefox.instance = None
        context.firefox_app = None
        found_app = MagicMock()
        calls = [0]

        def fake_app(name):
            calls[0] += 1
            if calls[0] < 2:
                raise RuntimeError("transient bus disconnect")
            return found_app

        m.tree.root.application = MagicMock(side_effect=fake_app)
        assert m._firefox_app(context, timeout=1.0) is found_app
        assert context.firefox_app is found_app

    def test_raises_assertion_when_all_names_fail(self):
        m = _import_firefox_steps()
        context = MagicMock(spec=[])
        m.tree.root.application = MagicMock(side_effect=RuntimeError("not found"))
        import pytest  # noqa: PLC0415
        with pytest.raises(AssertionError, match="not found via AT-SPI"):
            m._firefox_app(context, timeout=0.1)


# ---------------------------------------------------------------------------
# Accessibility launch environment
# ---------------------------------------------------------------------------

class _FakeNode:
    """Minimal dogtail node stand-in supporting findChildren over descendants."""

    def __init__(self, role_name, showing=True, children=(), name=""):
        self.roleName = role_name
        self.showing = showing
        self.children = list(children)
        self.name = name

    def findChildren(self, predicate):  # noqa: N802 — dogtail API name
        found = []
        for child in self.children:
            if predicate(child):
                found.append(child)
            found.extend(child.findChildren(predicate))
        return found

    def findChild(self, predicate):  # noqa: N802 — dogtail API name
        matches = self.findChildren(predicate)
        return matches[0] if matches else None


class TestFirefoxA11yEnv:
    def test_sets_gnome_accessibility(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_A11Y_ENV["GNOME_ACCESSIBILITY"] == "1"

    def test_sets_accessibility_enabled(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_A11Y_ENV["ACCESSIBILITY_ENABLED"] == "1"

    def test_disables_vm_local_p2p_accessibility_socket(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_A11Y_ENV["ATSPI_DISABLE_P2P"] == "1"

    def test_launch_clears_stale_accessibility_nodes(self):
        m = _import_firefox_steps()
        context = MagicMock()
        context.firefox_app = object()
        context.firefox_window = object()
        m.launch_firefox_via_command(context)
        _, kwargs = m.launch_background.call_args
        assert kwargs["env"] == m.FIREFOX_A11Y_ENV
        assert context.firefox_app is None
        assert context.firefox_window is None



# ---------------------------------------------------------------------------
# _firefox_window — false-pass guard
# ---------------------------------------------------------------------------

class TestFirefoxWindow:
    @staticmethod
    def _context_with(m, window):
        context = MagicMock()
        app = _FakeNode("application", children=[window], name="Firefox")
        m.tree.root.applications = MagicMock(return_value=[app])
        return context

    def test_returns_frame_with_populated_tree(self):
        m = _import_firefox_steps()
        window = _FakeNode("frame", children=[_FakeNode("entry")])
        assert m._firefox_window(self._context_with(m, window)) is window

    def test_accepts_filler_when_tree_is_populated(self):
        m = _import_firefox_steps()
        window = _FakeNode("filler", children=[_FakeNode("page tab list")])
        assert m._firefox_window(self._context_with(m, window)) is window

    def test_rejects_empty_filler(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        window = _FakeNode("filler")
        with pytest.raises(AssertionError, match="GNOME_ACCESSIBILITY"):
            m._firefox_window(self._context_with(m, window))

    def test_rejects_empty_frame(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        window = _FakeNode("frame")
        with pytest.raises(AssertionError, match="AT-SPI subtree is incomplete"):
            m._firefox_window(self._context_with(m, window))

    def test_prefers_frame_over_filler(self):
        m = _import_firefox_steps()
        filler = _FakeNode("filler", children=[_FakeNode("entry")])
        frame = _FakeNode("frame", children=[_FakeNode("entry")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[filler, frame])
        assert m._firefox_window(context) is frame

    def test_ignores_crash_reporter_window_and_selects_browser_window(self):
        m = _import_firefox_steps()
        crash_reporter = _FakeNode(
            "frame",
            showing=True,
            name="Tab crash reporter — Mozilla Firefox",
            children=[
                _FakeNode("entry", showing=True, name="Optional comments"),
                _FakeNode("page tab list", showing=True, children=[
                    _FakeNode("page tab", showing=True, name="Tab crash reporter"),
                ]),
            ],
        )
        browser_window = _FakeNode(
            "frame",
            showing=True,
            name="Mozilla Firefox",
            children=[
                _FakeNode("combo box", showing=True, name="Search with Google or enter address"),
                _FakeNode("page tab list", showing=True, children=[
                    _FakeNode("page tab", showing=True, name="Start Page"),
                ]),
            ],
        )
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[crash_reporter, browser_window])
        assert m._firefox_window(context) is browser_window


    def test_recognizes_combo_box_as_browser_chrome(self):
        m = _import_firefox_steps()
        frame = _FakeNode("frame", showing=True, children=[
            _FakeNode("combo box", showing=True, name="Search with Google or enter address")
        ])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[frame])
        assert m._firefox_window(context) is frame

    def test_prefers_filler_with_chrome_over_frameless_subframe(self):
        m = _import_firefox_steps()
        filler = _FakeNode("filler", children=[_FakeNode("entry")])
        subframe = _FakeNode("frame", children=[_FakeNode("push button")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[filler, subframe])
        assert m._firefox_window(context) is filler

    def test_rejects_populated_frame_without_browser_chrome(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        frame = _FakeNode("frame", children=[_FakeNode("tool bar")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[frame])
        with pytest.raises(AssertionError, match="subtree is incomplete"):
            m._firefox_window(context)

    def test_rejects_populated_filler_without_browser_chrome(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        filler = _FakeNode("filler", children=[_FakeNode("tool bar")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[filler])
        with pytest.raises(AssertionError, match="subtree is incomplete"):
            m._firefox_window(context)

    def test_liveness_check_accepts_empty_window(self):
        m = _import_firefox_steps()
        window = _FakeNode("filler")
        result = m._firefox_window(self._context_with(m, window), require_a11y_tree=False)
        assert result is window

    def test_no_window_reports_not_found(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        context = MagicMock()
        context.firefox.instance = _FakeNode("application")
        with pytest.raises(AssertionError, match="main window not found"):
            m._firefox_window(context)

    def test_ignores_hidden_windows(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        hidden = _FakeNode("frame", showing=False, children=[_FakeNode("entry")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[hidden])
        with pytest.raises(AssertionError, match="main window not found"):
            m._firefox_window(context)


class TestWindowCandidates:
    def test_top_level_children_preferred(self):
        m = _import_firefox_steps()
        top_window = _FakeNode("frame", showing=True)
        nested_frame = _FakeNode("frame", showing=True)
        top_window.children = [nested_frame]
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[top_window])
        candidates = m._window_candidates(context)
        assert candidates == [top_window]

    def test_falls_back_to_find_children_when_no_top_level(self):
        m = _import_firefox_steps()
        nested = _FakeNode("frame", showing=True)
        intermediate = _FakeNode("panel", showing=True, children=[nested])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[intermediate])
        candidates = m._window_candidates(context)
        assert candidates == [nested]


class TestAddressBar:
    def test_finds_entry_role(self):
        m = _import_firefox_steps()
        bar = _FakeNode("entry", showing=True, name="Search or enter address")
        window = _FakeNode("frame", showing=True, children=[bar])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        assert m._address_bar(context) is bar

    def test_finds_autocomplete_role(self):
        m = _import_firefox_steps()
        bar = _FakeNode("autocomplete", showing=True, name="Search with Google or enter address")
        window = _FakeNode("frame", showing=True, children=[bar])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        assert m._address_bar(context) is bar

    def test_finds_combo_box_role(self):
        m = _import_firefox_steps()
        bar = _FakeNode("combo box", showing=True, name="Search with Google or enter address")
        window = _FakeNode("frame", showing=True, children=[bar])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        assert m._address_bar(context) is bar

    def test_matches_url_keyword(self):
        m = _import_firefox_steps()
        other_entry = _FakeNode("entry", showing=True, name="Username")
        url_entry = _FakeNode("entry", showing=True, name="Website URL")
        window = _FakeNode("frame", showing=True, children=[other_entry, url_entry])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        assert m._address_bar(context) is url_entry

    def test_navigate_firefox_to_fallback_on_typing_error(self):
        m = _import_firefox_steps()
        bar = _FakeNode("combo box", showing=True, name="Search with Google or enter address")
        bar.text = "start.fedoraproject.org"
        window = _FakeNode("frame", showing=True, children=[bar])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock(side_effect=TypeError("cannot unpack"))
        m.atspi_click = MagicMock()

        def fake_popen(cmd, **kw):
            setattr(bar, "text", "about:blank")
            return MagicMock()

        with patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
            m.navigate_firefox_to(context, "about:blank")
            assert "about:blank" in bar.text
            assert mock_popen.called


class TestTabCount:
    def test_counts_tabs_correctly(self):
        m = _import_firefox_steps()
        tab1 = _FakeNode("page tab", showing=True)
        tab2 = _FakeNode("page tab", showing=True)
        tab_list = _FakeNode("page tab list", showing=True, children=[tab1, tab2])
        window = _FakeNode("frame", showing=True, children=[tab_list])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        assert m._tab_count(context) == 2

    def test_firefox_tab_count_increases_fallback_via_button(self):
        m = _import_firefox_steps()
        context = MagicMock()
        tabs = [_FakeNode("page tab", showing=True)]
        tab_list = _FakeNode("page tab list", showing=True, children=tabs)
        new_tab_btn = _FakeNode("button", showing=True, name="Open a new tab (Ctrl+T)")

        def fake_click(node):
            if node is new_tab_btn:
                new_tab = _FakeNode("page tab", showing=True)
                tabs.append(new_tab)
                tab_list.children = list(tabs)

        m.atspi_click = MagicMock(side_effect=fake_click)

        window = _FakeNode("frame", showing=True, children=[tab_list, new_tab_btn])
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock()

        m.firefox_tab_count_increases(context)
        assert len(tabs) == 2
        m.atspi_click.assert_called_once_with(new_tab_btn)

    def test_firefox_tab_count_decreases_fallback_via_button(self):
        m = _import_firefox_steps()
        context = MagicMock()
        close_btn = _FakeNode("button", showing=True, name="Close tab")
        tab1 = _FakeNode("page tab", showing=True)
        tab2 = _FakeNode("page tab", showing=True, children=[close_btn])
        tabs = [tab1, tab2]
        tab_list = _FakeNode("page tab list", showing=True, children=tabs)

        def fake_click(node):
            if node is close_btn:
                tabs.pop()
                tab_list.children = list(tabs)

        m.atspi_click = MagicMock(side_effect=fake_click)

        window = _FakeNode("frame", showing=True, children=[tab_list])
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock()

        m.firefox_tab_count_decreases(context)
        assert len(tabs) == 1
        m.atspi_click.assert_called_once_with(close_btn)

    def test_tab_increase_does_not_pass_without_observed_change(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        tab = _FakeNode("page tab", showing=True)
        tab_list = _FakeNode("page tab list", showing=True, children=[tab])
        window = _FakeNode("frame", showing=True, children=[tab_list])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock(side_effect=RuntimeError("no input"))
        m.sleep = MagicMock()

        with pytest.raises(AssertionError, match="did not increase"):
            m.firefox_tab_count_increases(context)

    def test_tab_decrease_does_not_pass_without_observed_change(self):
        import pytest  # noqa: PLC0415
        m = _import_firefox_steps()
        tabs = [_FakeNode("page tab", showing=True), _FakeNode("page tab", showing=True)]
        tab_list = _FakeNode("page tab list", showing=True, children=tabs)
        window = _FakeNode("frame", showing=True, children=[tab_list])
        context = MagicMock(firefox_tab_count=2)
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock(side_effect=RuntimeError("no input"))
        m.sleep = MagicMock()

        with pytest.raises(AssertionError, match="did not decrease"):
            m.firefox_tab_count_decreases(context)


class TestLaunchTargetOrdering:
    def test_flatpak_precedes_exported_desktop_entry(self):
        m = _import_firefox_steps()
        targets = list(m.FIREFOX_LAUNCH_TARGETS)
        assert targets.index(("flatpak", "org.mozilla.firefox")) < targets.index(
            ("desktop", "org.mozilla.firefox.desktop")
        )


class TestCharacterInput:
    def test_char_to_uinput_event_maps_colon(self):
        import tests.smoke.features.environment as env
        res = env._char_to_uinput_event(":")
        assert res is not None
        key_event, shifted = res
        assert shifted is True

    def test_char_to_uinput_event_maps_uppercase(self):
        import tests.smoke.features.environment as env
        res = env._char_to_uinput_event("B")
        assert res is not None
        key_event, shifted = res
        assert shifted is True

    def test_char_to_uinput_event_maps_hyphen(self):
        import tests.smoke.features.environment as env
        res = env._char_to_uinput_event("-")
        assert res is not None
        key_event, shifted = res
        assert shifted is False

    def test_type_text_uinput_handles_about_blank(self):
        import tests.smoke.features.environment as env
        device = MagicMock()
        env._emit_characters_to_device(device, "about:blank")
        assert device.emit_click.called
        assert device.emit.called  # Shift for colon

    def test_type_text_uinput_handles_url(self):
        import tests.smoke.features.environment as env
        device = MagicMock()
        env._emit_characters_to_device(device, "https://projectbluefin.io")
        assert device.emit_click.called

    def test_key_name_map_maps_return_to_enter(self):
        import tests.smoke.features.environment as env
        assert env._KEY_NAME_MAP["return"] == "ENTER"
        assert env._KEY_NAME_MAP["enter"] == "ENTER"


class TestFirefoxNavigationAndClose:
    def test_navigate_firefox_to_matches_prefix_stripped_url(self):
        m = _import_firefox_steps()
        bar = _FakeNode("combo box", showing=True, name="Search with Google or enter address")
        bar.text = "projectbluefin.io"
        window = _FakeNode("frame", showing=True, children=[bar])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock()

        m.navigate_firefox_to(context, "https://projectbluefin.io")


    def test_navigate_firefox_to_matches_about_blank_empty_bar(self):
        m = _import_firefox_steps()
        bar = _FakeNode("combo box", showing=True, name="Search with Google or enter address")
        bar.text = ""
        doc = _FakeNode("document web", showing=True, name="about:blank")
        window = _FakeNode("frame", showing=True, children=[bar, doc])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
        context.execute_steps = MagicMock()

        m.navigate_firefox_to(context, "about:blank")

    def test_firefox_is_no_longer_running_fallback(self):
        m = _import_firefox_steps()
        app = _FakeNode("application")
        frame = _FakeNode("frame", showing=True)
        app.children = [frame]
        m.tree.root.application = MagicMock(return_value=app)
        context = MagicMock()

        # Simulate frame disappearing after fallback killall
        def fake_run(cmd, **kw):
            if "killall" in cmd:
                app.children = []

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            m.firefox_is_no_longer_running(context)
            assert mock_run.called
