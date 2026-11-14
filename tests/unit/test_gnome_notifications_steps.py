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


def _reply(state: dict) -> str:
    """A Shell.Eval reply carrying ``state`` the way GNOME Shell encodes it."""
    import json

    literal = json.dumps(json.dumps(state)).replace("\\", "\\\\").replace("'", "\\'")
    return f"(true, '{literal}')\n"


def _runner(outputs):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return _Done(outputs[min(len(calls) - 1, len(outputs) - 1)])

    return run, calls


def _context(**attrs):
    return type("C", (), dict({"test_notification_title": "Test Notification ab12cd34",
                              "test_notification_seen": True, "notification_id": 7}, **attrs))()


GONE = {"shown": False, "queued": False, "error": None}
SHOWN = {"shown": True, "queued": True, "error": None}
QUEUED = {"shown": False, "queued": True, "error": None}
BROKEN = {"shown": False, "queued": False, "error": "TypeError: t.getSources is not a function"}


def test_parse_reads_the_reply_shell_sends():
    module = _import_gnome_notifications_steps()
    assert module._parse_eval_json(_reply(QUEUED)) == QUEUED
    assert module._parse_eval_json("(false, '')") is None
    assert module._parse_eval_json("(true, '\"not json\"')") is None


def test_banner_check_tracks_the_test_notification_not_any_banner():
    # GNOME Shell holds an unrelated banner on screen while the session is
    # idle, and GNOME 51 keeps _bannerBin visible with no banner (#827 audit
    # row 10), so the check is about this scenario's notification only.
    module = _import_gnome_notifications_steps()
    js = module.banner_gone_js("Test Notification ab12cd34")
    assert "_bannerBin" not in js
    assert 'const title = "Test Notification ab12cd34"' in js
    assert "catch (e) { error = String(e); }" in js


def test_each_sent_notification_gets_a_unique_checked_title(monkeypatch):
    # Other scenarios (and retries) leave same-titled notifications in the
    # tray, so the dismissal check needs this send's own title.
    module = _import_gnome_notifications_steps()
    sent = []
    monkeypatch.setattr(module, "_run", lambda cmd: (sent.append(cmd) or "(uint32 7,)", 0, ""))
    monkeypatch.setattr(module, "sleep", lambda s: None)
    first, second = type("C", (), {})(), type("C", (), {})()
    module.send_test_desktop_notification(first)
    module.send_test_desktop_notification(second)
    assert first.test_notification_title != second.test_notification_title
    assert first.test_notification_title.startswith(module.TEST_NOTIFICATION_TITLE + " ")
    assert f"'{first.test_notification_title}'" in sent[0]


def test_check_passes_once_the_notification_is_gone():
    module = _import_gnome_notifications_steps()
    run, calls = _runner([_reply(SHOWN), _reply(GONE)])
    module.notification_banner_no_longer_showing(_context(), run=run, pause=lambda s: None)
    assert len(calls) == 2


def test_check_fails_instead_of_force_dismissing():
    module = _import_gnome_notifications_steps()
    run, calls = _runner([_reply(SHOWN)])
    with pytest.raises(AssertionError, match="still shown or queued"):
        module.notification_banner_no_longer_showing(_context(), run=run, pause=lambda s: None)
    assert all("destroy()" not in " ".join(c) and "hide()" not in " ".join(c) for c in calls)
    assert len(calls) == module.BANNER_DISMISS_TIMEOUT_S * 2


def test_a_tray_read_error_is_never_gone():
    # The JS reports the error rather than shown/queued false: an API change in
    # Shell must not read as "dismissed" (fresh-context review of #1209).
    module = _import_gnome_notifications_steps()
    run, _ = _runner([_reply(BROKEN)])
    with pytest.raises(AssertionError, match="getSources is not a function"):
        module.notification_banner_no_longer_showing(_context(), run=run, pause=lambda s: None)


def test_a_failed_shell_eval_is_never_gone():
    module = _import_gnome_notifications_steps()
    run, _ = _runner(["(false, '')\n"])
    with pytest.raises(AssertionError, match="unusable Shell.Eval reply"):
        module.notification_banner_no_longer_showing(_context(), run=run, pause=lambda s: None)


def test_check_without_a_sent_notification_fails():
    # Nothing sends the bare prefix any more, so defaulting to it always passed.
    module = _import_gnome_notifications_steps()
    run, calls = _runner([_reply(GONE)])
    with pytest.raises(AssertionError, match="No test notification was sent"):
        module.notification_banner_no_longer_showing(type("C", (), {})(), run=run, pause=lambda s: None)
    assert calls == []


def test_check_without_seeing_the_notification_first_fails():
    module = _import_gnome_notifications_steps()
    run, _ = _runner([_reply(GONE)])
    with pytest.raises(AssertionError, match="not seen before CloseNotification"):
        module.notification_banner_no_longer_showing(
            _context(test_notification_seen=False), run=run, pause=lambda s: None
        )


def test_dismiss_closes_only_after_seeing_the_notification(monkeypatch):
    module = _import_gnome_notifications_steps()
    closed = []
    monkeypatch.setattr(module, "_run", lambda cmd: (closed.append(cmd) or "", 0, ""))
    run, calls = _runner([_reply(GONE), _reply(QUEUED)])
    context = _context(test_notification_seen=False)
    module.dismiss_notification_via_gdbus(context, run=run, pause=lambda s: None)
    assert len(calls) == 2 and context.test_notification_seen is True
    assert closed and "CloseNotification 7" in closed[0]


def test_dismiss_refuses_when_the_tray_cannot_be_read(monkeypatch):
    module = _import_gnome_notifications_steps()
    closed = []
    monkeypatch.setattr(module, "_run", lambda cmd: (closed.append(cmd) or "", 0, ""))
    run, _ = _runner([_reply(BROKEN)])
    with pytest.raises(AssertionError, match="was never seen"):
        module.dismiss_notification_via_gdbus(_context(test_notification_seen=False), run=run, pause=lambda s: None)
    assert closed == []
