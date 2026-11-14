"""Unit tests for tests/smoke/features/steps/gnome_notifications_steps.py."""

import sys
import types

import pytest


def _import_gnome_notifications_steps():
    """Import the module under test with lightweight behave/qecore stubs."""
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)

    qecore_stub = types.ModuleType("qecore")
    common_steps_stub = types.ModuleType("qecore.common_steps")
    common_steps_stub.__all__ = []
    qecore_stub.common_steps = common_steps_stub

    sys.modules["behave"] = behave_stub
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = common_steps_stub
    sys.modules.pop("tests.smoke.features.steps.gnome_notifications_steps", None)

    import tests.smoke.features.steps.gnome_notifications_steps as module

    return module


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("(uint32 5,)", 5),
        ("(uint32  12,)", 12),
        ("noise before (uint32 42,) noise after", 42),
    ],
)
def test_parse_notification_id_returns_expected_value(output, expected):
    module = _import_gnome_notifications_steps()

    assert module._parse_notification_id(output) == expected


@pytest.mark.parametrize("output", ["no notification id here", ""])
def test_parse_notification_id_raises_on_unparseable_output(output):
    module = _import_gnome_notifications_steps()

    with pytest.raises(AssertionError, match="Could not parse"):
        module._parse_notification_id(output)


class _Done:
    def __init__(self, stdout):
        self.stdout = stdout


def _runner(outputs):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _Done(outputs[min(len(calls) - 1, len(outputs) - 1)])

    return run, calls


def test_banner_check_tracks_the_test_notification_not_any_banner():
    # GNOME Shell holds an unrelated banner on screen while the session is
    # idle, and GNOME 51 keeps _bannerBin visible with no banner (#827 audit
    # row 10), so the check is about this scenario's notification only.
    module = _import_gnome_notifications_steps()
    js = module.banner_gone_js("Test Notification ab12cd34")
    assert "_bannerBin" not in js
    assert 'const title = "Test Notification ab12cd34"' in js
    assert "b.notification.title === title" in js
    assert "getSources()" in js


def test_each_sent_notification_gets_a_unique_checked_title(monkeypatch):
    # Other scenarios (and retries) leave same-titled notifications in the
    # tray, so the dismissal check needs this send's own title.
    module = _import_gnome_notifications_steps()
    sent = []
    monkeypatch.setattr(module, "_run", lambda cmd: (sent.append(cmd) or "(uint32 7,)", 0, ""))
    first, second = type("C", (), {})(), type("C", (), {})()
    module.send_test_desktop_notification(first)
    module.send_test_desktop_notification(second)
    assert first.test_notification_title != second.test_notification_title
    assert first.test_notification_title.startswith(module.TEST_NOTIFICATION_TITLE + " ")
    assert f"'{first.test_notification_title}'" in sent[0]


def test_banner_gone_returns_as_soon_as_shell_says_so():
    module = _import_gnome_notifications_steps()
    run, calls = _runner([
        '(true, \'"{\\\\"gone\\\\":false,\\\\"shown\\\\":true}"\')',
        '(true, \'"{\\\\"gone\\\\":true,\\\\"shown\\\\":false}"\')',
    ])
    module.notification_banner_no_longer_showing(type("C", (), {"test_notification_title": "Test Notification x"})(), run=run, pause=lambda s: None)
    assert len(calls) == 2


def test_banner_still_showing_fails_instead_of_force_dismissing():
    module = _import_gnome_notifications_steps()
    run, calls = _runner(['(true, \'"{\\\\"gone\\\\":false,\\\\"shown\\\\":true}"\')'])
    with pytest.raises(AssertionError, match="still shown or queued"):
        module.notification_banner_no_longer_showing(type("C", (), {"test_notification_title": "Test Notification x"})(), run=run, pause=lambda s: None)
    assert all("destroy()" not in " ".join(c) and "hide()" not in " ".join(c) for c in calls)
    assert len(calls) == module.BANNER_DISMISS_TIMEOUT_S * 2
