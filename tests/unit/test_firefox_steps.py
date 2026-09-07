"""Unit tests for firefox_steps.py pure helper functions."""
import sys
import types
from unittest.mock import MagicMock


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
    sys.modules["dogtail.tree"] = tree_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    app_support_stub = types.ModuleType("app_support")
    app_support_stub.launch_background = MagicMock()
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


# ---------------------------------------------------------------------------
# _firefox_app — context instance cache
# ---------------------------------------------------------------------------

class TestFirefoxApp:
    def test_returns_cached_instance_when_set(self):
        m = _import_firefox_steps()
        cached = MagicMock()
        context = MagicMock()
        context.firefox.instance = cached
        assert m._firefox_app(context) is cached

    def test_fallback_when_instance_is_none(self):
        m = _import_firefox_steps()
        context = MagicMock()
        context.firefox.instance = None
        found_app = MagicMock()
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

    def test_raises_assertion_when_all_names_fail(self):
        m = _import_firefox_steps()
        context = MagicMock(spec=[])
        m.tree.root.application = MagicMock(side_effect=RuntimeError("not found"))
        import pytest  # noqa: PLC0415
        with pytest.raises(AssertionError, match="not found via AT-SPI"):
            m._firefox_app(context)


# ---------------------------------------------------------------------------
# Accessibility launch environment
# ---------------------------------------------------------------------------

class _FakeNode:
    """Minimal dogtail node stand-in supporting findChildren over descendants."""

    def __init__(self, role_name, showing=True, children=()):
        self.roleName = role_name
        self.showing = showing
        self.children = list(children)

    def findChildren(self, predicate):  # noqa: N802 — dogtail API name
        found = []
        for child in self.children:
            if predicate(child):
                found.append(child)
            found.extend(child.findChildren(predicate))
        return found


class TestFirefoxA11yEnv:
    def test_sets_gnome_accessibility(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_A11Y_ENV["GNOME_ACCESSIBILITY"] == "1"

    def test_sets_accessibility_enabled(self):
        m = _import_firefox_steps()
        assert m.FIREFOX_A11Y_ENV["ACCESSIBILITY_ENABLED"] == "1"

    def test_launch_passes_a11y_env(self):
        m = _import_firefox_steps()
        context = MagicMock()
        m.launch_firefox_via_command(context)
        _, kwargs = m.launch_background.call_args
        assert kwargs["env"] == m.FIREFOX_A11Y_ENV


# ---------------------------------------------------------------------------
# _firefox_window — false-pass guard
# ---------------------------------------------------------------------------

class TestFirefoxWindow:
    @staticmethod
    def _context_with(m, window):
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[window])
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
        with pytest.raises(AssertionError, match="AT-SPI subtree is empty"):
            m._firefox_window(self._context_with(m, window))

    def test_prefers_frame_over_filler(self):
        m = _import_firefox_steps()
        filler = _FakeNode("filler", children=[_FakeNode("entry")])
        frame = _FakeNode("frame", children=[_FakeNode("entry")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[filler, frame])
        assert m._firefox_window(context) is frame

    def test_prefers_filler_with_chrome_over_frameless_subframe(self):
        m = _import_firefox_steps()
        filler = _FakeNode("filler", children=[_FakeNode("entry")])
        subframe = _FakeNode("frame", children=[_FakeNode("push button")])
        context = MagicMock()
        context.firefox.instance = _FakeNode("application", children=[filler, subframe])
        assert m._firefox_window(context) is filler

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


class TestLaunchTargetOrdering:
    def test_flatpak_precedes_exported_desktop_entry(self):
        m = _import_firefox_steps()
        targets = list(m.FIREFOX_LAUNCH_TARGETS)
        assert targets.index(("flatpak", "org.mozilla.firefox")) < targets.index(
            ("desktop", "org.mozilla.firefox.desktop")
        )
