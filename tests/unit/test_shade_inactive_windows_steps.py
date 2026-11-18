"""Regression coverage for the shared shade setup's failure reporting.

The shade scenarios share one setup step that opens fresh Text Editor and
Calculator windows and waits for each to become ready. Before this coverage a
failed wait raised a generic "Shell condition not reached" that named neither
the application nor which window-readiness condition failed (absent window,
wrong window count, unmapped, or not fully opaque). The two helpers below make
that failure specific.
"""

import sys
from types import SimpleNamespace

import pytest

from tests.extensions.features.steps.shade_inactive_windows_steps import (
    _window_readiness_failure,
    launch_application_windows,
)


# ---------------------------------------------------------------------------
# Pure failure-message helper
# ---------------------------------------------------------------------------

class TestWindowReadinessFailure:
    def test_absent_window_names_the_application(self):
        message = _window_readiness_failure("Text Editor", {"count": 0, "mapped": None, "opacity": None})
        assert "Text Editor" in message
        assert "no window opened" in message

    def test_wrong_window_count_names_the_count(self):
        message = _window_readiness_failure("Calculator", {"count": 2, "mapped": True, "opacity": 255})
        assert "Calculator" in message
        assert "instead of exactly one" in message

    def test_unmapped_window(self):
        message = _window_readiness_failure("Text Editor", {"count": 1, "mapped": False, "opacity": None})
        assert "never mapped" in message

    def test_not_fully_opaque_window_reports_the_opacity(self):
        message = _window_readiness_failure("Calculator", {"count": 1, "mapped": True, "opacity": 200})
        assert "not fully opaque" in message
        assert "200" in message


# ---------------------------------------------------------------------------
# Integration: the shared setup step reports the failing application
# ---------------------------------------------------------------------------

class _FakeExtension:
    """A guest that launches the app but never reaches the readiness condition."""

    def __init__(self, readiness_state):
        self._readiness_state = readiness_state

    def shell_json(self, expression):
        # The readiness probe is the only call carrying a `count` property.
        # Every other call is the pre-launch "no existing window" probe.
        if "count" in expression:
            return self._readiness_state
        return 0

    def wait_for(self, expression, expected=True, timeout=10):
        raise AssertionError("Shell condition not reached: ...")


def _install_fake_gi(monkeypatch):
    gi = SimpleNamespace(require_version=lambda name, version: None)
    app_info = SimpleNamespace(new=lambda desktop_id: SimpleNamespace(launch=lambda *a, **k: True))
    gi.repository = SimpleNamespace(Gio=SimpleNamespace(DesktopAppInfo=app_info))
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", gi.repository)


def test_launch_reports_the_application_and_condition_that_failed(monkeypatch):
    _install_fake_gi(monkeypatch)
    extension = _FakeExtension({"count": 0, "mapped": None, "opacity": None})
    context = SimpleNamespace(extension=extension, shade_windows={}, extension_cleanups=[])

    with pytest.raises(AssertionError, match="Text Editor.*no window opened"):
        launch_application_windows(context)
