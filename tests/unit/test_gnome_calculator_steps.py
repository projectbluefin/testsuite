"""Unit tests for gnome_calculator_steps.py pure helper functions."""
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_calculator_steps(tree_available: bool = True):
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
        if "gnome_calculator_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.gnome_calculator_steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestCalculatorConstants:
    def test_app_names_is_tuple(self):
        m = _import_calculator_steps()
        assert isinstance(m.CALCULATOR_APP_NAMES, tuple)
        assert "gnome-calculator" in m.CALCULATOR_APP_NAMES

    def test_button_roles_is_set(self):
        m = _import_calculator_steps()
        assert isinstance(m.BUTTON_ROLES, set)
        assert "push button" in m.BUTTON_ROLES

    def test_display_roles_is_set(self):
        m = _import_calculator_steps()
        assert isinstance(m.DISPLAY_ROLES, set)
        assert "text" in m.DISPLAY_ROLES

    def test_button_aliases_is_dict(self):
        m = _import_calculator_steps()
        assert isinstance(m.BUTTON_ALIASES, dict)
        assert "+" in m.BUTTON_ALIASES
        assert "=" in m.BUTTON_ALIASES
        assert "clear" in m.BUTTON_ALIASES

    def test_button_aliases_plus_has_plus_symbol(self):
        m = _import_calculator_steps()
        assert "+" in m.BUTTON_ALIASES["+"]

    def test_button_aliases_equals_has_equals_word(self):
        m = _import_calculator_steps()
        assert "equals" in m.BUTTON_ALIASES["="]


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_strips_whitespace(self):
        m = _import_calculator_steps()
        assert m._normalize("  5  ") == "5"

    def test_casefolds(self):
        m = _import_calculator_steps()
        assert m._normalize("CLEAR") == "clear"

    def test_replaces_em_dash_with_hyphen(self):
        m = _import_calculator_steps()
        assert m._normalize("−") == "-"

    def test_replaces_en_dash_with_hyphen(self):
        m = _import_calculator_steps()
        assert m._normalize("–") == "-"

    def test_returns_empty_string_for_none(self):
        m = _import_calculator_steps()
        assert m._normalize(None) == ""  # type: ignore[arg-type]

    def test_returns_empty_string_for_empty(self):
        m = _import_calculator_steps()
        assert m._normalize("") == ""

    def test_leaves_digits_unchanged(self):
        m = _import_calculator_steps()
        assert m._normalize("42") == "42"

    def test_normalizes_combined(self):
        m = _import_calculator_steps()
        assert m._normalize("  AC  ") == "ac"


# ---------------------------------------------------------------------------
# _button_targets
# ---------------------------------------------------------------------------

class TestButtonTargets:
    def test_returns_set(self):
        m = _import_calculator_steps()
        result = m._button_targets("5")
        assert isinstance(result, set)

    def test_digit_maps_to_itself(self):
        m = _import_calculator_steps()
        result = m._button_targets("5")
        assert "5" in result

    def test_plus_maps_to_aliases(self):
        m = _import_calculator_steps()
        result = m._button_targets("+")
        assert "plus" in result or "+" in result

    def test_equals_maps_to_equals_word(self):
        m = _import_calculator_steps()
        result = m._button_targets("=")
        assert "equals" in result

    def test_clear_maps_to_ac(self):
        m = _import_calculator_steps()
        result = m._button_targets("clear")
        assert "ac" in result

    def test_normalized_alias_lookup(self):
        m = _import_calculator_steps()
        # "CLEAR" should also find clear's aliases
        result = m._button_targets("CLEAR")
        assert "ac" in result or "clear" in result

    def test_divide_slash_maps_to_divide(self):
        m = _import_calculator_steps()
        result = m._button_targets("÷")
        assert "divide" in result or "/" in result

    def test_subtract_maps_to_minus(self):
        m = _import_calculator_steps()
        result = m._button_targets("-")
        assert "minus" in result or "-" in result


# ---------------------------------------------------------------------------
# _skip_if_no_atspi
# ---------------------------------------------------------------------------

class TestSkipIfNoAtspi:
    def test_returns_false_when_tree_available(self):
        m = _import_calculator_steps()
        assert m._skip_if_no_atspi(MagicMock()) is False

    def test_returns_true_when_tree_is_none(self):
        m = _import_calculator_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        assert m._skip_if_no_atspi(context) is True

    def test_skip_message_contains_atspi(self):
        m = _import_calculator_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        assert "AT-SPI" in context.scenario.skip.call_args[0][0]


# ---------------------------------------------------------------------------
# calculator_is_no_longer_running
# ---------------------------------------------------------------------------

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


class TestCalculatorIsNoLongerRunning:
    def _run(self, monkeypatch, apps):
        m = _import_calculator_steps()
        clock = types.SimpleNamespace(now=0.0)
        root = _RetryingRoot(clock, apps)
        monkeypatch.setattr(m, "tree", types.SimpleNamespace(root=root))
        monkeypatch.setattr(m, "sleep", lambda s: setattr(clock, "now", clock.now + s))
        return m, clock, root

    def test_missing_app_returns_without_retrying_lookup(self, monkeypatch):
        m, clock, root = self._run(monkeypatch, [])
        m.calculator_is_no_longer_running(MagicMock())
        assert clock.now == 0.0
        assert root.application_calls == []

    def test_app_without_visible_frames_counts_as_closed(self, monkeypatch):
        m, clock, root = self._run(monkeypatch, [_App("Calculator")])
        m.calculator_is_no_longer_running(MagicMock())
        assert clock.now == 0.0

    def test_visible_app_fails_within_nominal_budget(self, monkeypatch):
        m, clock, root = self._run(monkeypatch, [_App("gnome-calculator", [_Frame()])])
        with pytest.raises(AssertionError, match="GNOME Calculator is still visible"):
            m.calculator_is_no_longer_running(MagicMock())
        assert clock.now == 10.0  # 20 polls x 0.5s, nothing multiplied
        assert root.application_calls == []
