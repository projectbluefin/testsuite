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


def test_banner_check_does_not_require_the_banner_bin_hidden():
    # GNOME 51 keeps Main.messageTray._bannerBin visible with no banner in it
    # (#827 audit row 10), so requiring it hidden made the check never pass.
    module = _import_gnome_notifications_steps()
    assert "_bannerBin" not in module.BANNER_GONE_JS
    assert "Main.messageTray._banner === null" in module.BANNER_GONE_JS


def test_banner_gone_returns_as_soon_as_shell_says_so():
    module = _import_gnome_notifications_steps()
    run, calls = _runner(["(true, 'false')", "(true, 'true')"])
    module.notification_banner_no_longer_showing(None, run=run, pause=lambda s: None)
    assert len(calls) == 2


def test_banner_still_showing_fails_instead_of_force_dismissing():
    module = _import_gnome_notifications_steps()
    run, calls = _runner(["(true, 'false')"])
    with pytest.raises(AssertionError, match="still showing"):
        module.notification_banner_no_longer_showing(None, run=run, pause=lambda s: None)
    assert all("destroy" not in " ".join(c) and "hide()" not in " ".join(c) for c in calls)
    assert len(calls) == module.BANNER_DISMISS_TIMEOUT_S * 2
