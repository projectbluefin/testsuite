"""Unit tests for tests/smoke/features/steps/gnome_settings_steps.py."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


MODULE_NAME = "tests.smoke.features.steps.gnome_settings_steps"


def _import_gnome_settings_steps():
    """Import the module under test with external GUI deps stubbed."""
    behave_stub = MagicMock()
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub
    sys.modules["behave.runner"] = MagicMock()

    dogtail_stub = MagicMock()
    dogtail_tree_stub = MagicMock()
    dogtail_stub.tree = dogtail_tree_stub
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = dogtail_tree_stub
    sys.modules["dogtail.utils"] = MagicMock()
    sys.modules["dogtail.rawinput"] = MagicMock()

    sys.modules["qecore"] = MagicMock()
    sys.modules["qecore.common_steps"] = MagicMock()

    app_support_stub = MagicMock()
    app_support_stub.launch_background = MagicMock(return_value="launch-target")
    app_support_stub._IN_CONTAINER = False
    app_support_stub._ssh_run = MagicMock()
    sys.modules["app_support"] = app_support_stub

    sys.modules.pop(MODULE_NAME, None)
    return importlib.import_module(MODULE_NAME)


class TestLooksLikeSystemInfo:
    def setup_method(self):
        self.mod = _import_gnome_settings_steps()

    def test_module_imports_with_stubbed_dependencies(self):
        assert self.mod.INFO_TOKENS == ("bluefin", "fedora", "linux", "version", "os")

    @pytest.mark.parametrize("token", ("bluefin", "fedora", "linux", "version", "os"))
    def test_returns_true_for_each_info_token(self, token):
        assert self.mod._looks_like_system_info(f"system {token} details") is True

    @pytest.mark.parametrize("token", ("bluefin", "fedora", "linux", "version", "os"))
    def test_is_case_insensitive_for_info_tokens(self, token):
        assert self.mod._looks_like_system_info(token.upper()) is True

    def test_returns_true_for_digits_without_tokens(self):
        assert self.mod._looks_like_system_info("build 41") is True

    def test_returns_true_when_text_has_token_and_digits(self):
        assert self.mod._looks_like_system_info("Bluefin Linux 41") is True

    def test_returns_false_for_empty_string(self):
        assert self.mod._looks_like_system_info("") is False

    def test_returns_false_for_text_without_tokens_or_digits(self):
        assert self.mod._looks_like_system_info("desktop details shown here") is False


class TestVisibleText:
    def setup_method(self):
        self.mod = _import_gnome_settings_steps()

    def test_prefers_node_name(self):
        node = MagicMock()
        node.name = "  About  "
        node.text = "ignored"

        assert self.mod._visible_text(node) == "About"

    def test_falls_back_to_text_when_name_is_blank(self):
        node = MagicMock()
        node.name = "   "
        node.text = "  Fedora Linux  "

        assert self.mod._visible_text(node) == "Fedora Linux"

    def test_returns_empty_string_when_text_access_raises(self):
        node = MagicMock()
        node.name = ""
        type(node).text = PropertyMock(side_effect=RuntimeError("boom"))

        assert self.mod._visible_text(node) == ""


class TestSkipIfNoAtspi:
    def setup_method(self):
        self.mod = _import_gnome_settings_steps()

    def test_skips_scenario_when_tree_is_unavailable(self):
        context = MagicMock()

        with patch.object(self.mod, "tree", None):
            assert self.mod._skip_if_no_atspi(context) is True

        context.scenario.skip.assert_called_once_with(
            "AT-SPI unavailable: dogtail not imported in this environment"
        )

    def test_returns_false_when_tree_is_available(self):
        context = MagicMock()

        with patch.object(self.mod, "tree", MagicMock()):
            assert self.mod._skip_if_no_atspi(context) is False

        context.scenario.skip.assert_not_called()


class TestSettingsApp:
    def setup_method(self):
        self.mod = _import_gnome_settings_steps()

    def test_finds_settings_via_applications_list(self):
        app = MagicMock()
        app.name = "gnome-control-center"
        self.mod.tree.root.applications = MagicMock(return_value=[app])

        result = self.mod._settings_app(timeout=1)
        assert result is app


class _RetryingRoot:
    """``tree.root`` whose per-name lookup costs dogtail's default retry wait."""

    def __init__(self, clock, apps=()):
        self.clock = clock
        self.apps = list(apps)
        self.application_calls = []

    def applications(self):
        return list(self.apps)

    def application(self, name):
        self.application_calls.append(name)
        self.clock.now += 10  # dogtail retries ~10s before raising
        raise LookupError(name)


class _Frame:
    roleName = "frame"
    showing = True


class _App:
    def __init__(self, name, frames=()):
        self.name = name
        self.frames = list(frames)

    def findChildren(self, predicate):  # noqa: N802 - dogtail API
        return [frame for frame in self.frames if predicate(frame)]


class TestSettingsIsNoLongerRunning:
    def _run(self, monkeypatch, apps):
        mod = _import_gnome_settings_steps()
        clock = SimpleNamespace(now=0.0)
        root = _RetryingRoot(clock, apps)
        monkeypatch.setattr(mod, "tree", SimpleNamespace(root=root))
        monkeypatch.setattr(mod, "sleep", lambda s: setattr(clock, "now", clock.now + s))
        monkeypatch.setattr(mod.shutil, "which", lambda _cmd: None)
        return mod, clock, root

    def test_settings_like_name_without_exact_alias_does_not_retry_lookup(self, monkeypatch):
        # The snapshot's substring match flags "running", but no exact alias is
        # registered: the per-name check must not pay dogtail's retry per alias.
        mod, clock, root = self._run(monkeypatch, [_App("Settings Daemon")])
        mod.settings_is_no_longer_running(MagicMock())
        assert clock.now == 0.5  # only the post-pkill settle
        assert root.application_calls == []

    def test_visible_settings_fails_within_nominal_budget(self, monkeypatch):
        mod, clock, root = self._run(monkeypatch, [_App("Settings", [_Frame()])])
        with pytest.raises(AssertionError, match="GNOME Settings is still visible"):
            mod.settings_is_no_longer_running(MagicMock())
        assert clock.now == 10.5  # settle + 20 polls x 0.5s, nothing multiplied
        assert root.application_calls == []
