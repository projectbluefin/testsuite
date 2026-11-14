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


def _eval_result(value: str):
    return types.SimpleNamespace(stdout=f"(true, '{value}')", returncode=0)


def _run_dismiss_check(module, outputs):
    from unittest.mock import patch

    with patch.object(module.subprocess, "run", side_effect=outputs), \
         patch.object(module, "sleep"):
        module.notification_banner_no_longer_showing(None)


def test_banner_check_reports_banner_closing_on_its_own(capsys):
    module = _import_gnome_notifications_steps()

    _run_dismiss_check(module, [_eval_result("false"), _eval_result("true")])

    assert "gnome-51-audit row 10: banner closed on its own within 0.5s" in capsys.readouterr().out


def test_banner_check_reports_force_dismiss(capsys):
    module = _import_gnome_notifications_steps()

    outputs = [_eval_result("false")] * 40 + [_eval_result("dismissed"), _eval_result("true")]
    _run_dismiss_check(module, outputs)

    assert "gnome-51-audit row 10: banner closed only after the Shell.Eval force-dismiss" in capsys.readouterr().out


def test_banner_check_reports_soft_pass_when_banner_stays(capsys):
    module = _import_gnome_notifications_steps()

    _run_dismiss_check(module, [_eval_result("false")] * 42)

    out = capsys.readouterr().out
    assert "gnome-51-audit row 10: banner still showing after the force-dismiss; step passes on a warning" in out
