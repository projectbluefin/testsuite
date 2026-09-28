"""Unit tests for smoke display-scaling command and assertion helpers."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.smoke.features.steps import display_scaling_steps


def _display_config_namespace(monkeypatch):
    """Load the embedded DisplayConfig helper without running its CLI entrypoint."""
    fake_dbus = SimpleNamespace(
        Dictionary=lambda value, signature: value,
        Boolean=bool,
        Int32=int,
        Int64=int,
        UInt32=int,
        UInt64=int,
        Double=float,
        String=str,
        Array=list,
    )
    monkeypatch.setitem(sys.modules, "dbus", fake_dbus)
    script = display_scaling_steps._DISPLAY_CONFIG_SCRIPT.split(
        "\naction = sys.argv[1]", maxsplit=1
    )[0]
    namespace = {}
    exec(script, namespace)
    return namespace


def test_display_config_repositions_logical_monitors_when_scaling(monkeypatch):
    namespace = _display_config_namespace(monkeypatch)
    monitor = (
        ("HDMI-1", "vendor", "product", "serial"),
        [("1920x1080", None, None, None, None, None, {"is-current": True})],
    )
    logical_monitor = (
        1920,
        1080,
        1.0,
        0,
        False,
        [("HDMI-1", "vendor", "product", "serial")],
    )

    result = namespace["_build_logical_monitor"](
        logical_monitor,
        {("HDMI-1", "vendor", "product", "serial"): monitor},
        1.5,
    )

    assert result[:3] == (1280, 720, 1.5)


def test_remote_session_commands_source_session_environment():
    with patch.object(display_scaling_steps, "_IN_CONTAINER", True):
        command = display_scaling_steps._with_session_env("gsettings get foo bar")

    assert command == "source /tmp/session.env 2>/dev/null; gsettings get foo bar"


def test_gsettings_get_sources_remote_session_environment():
    with (
        patch.object(display_scaling_steps, "_IN_CONTAINER", True),
        patch.object(
            display_scaling_steps,
            "_run_host",
            return_value=("@as ['scale-monitor-framebuffer']", 0, ""),
        ) as run_host,
    ):
        features, raw = display_scaling_steps._gsettings_get_features()

    assert features == ["scale-monitor-framebuffer"]
    assert raw == "@as ['scale-monitor-framebuffer']"
    run_host.assert_called_once_with(
        "source /tmp/session.env 2>/dev/null; "
        "gsettings get org.gnome.mutter experimental-features"
    )


def test_gsettings_get_treats_a_missing_key_as_nothing_to_enable():
    # GNOME 51 drops the experimental-features key once fractional scaling
    # graduates: "No such key" means enablement is unnecessary, not an error.
    with (
        patch.object(display_scaling_steps, "_IN_CONTAINER", True),
        patch.object(
            display_scaling_steps,
            "_run_host",
            return_value=(
                "",
                1,
                "No such key \u201cexperimental-features\u2019",
            ),
        ),
    ):
        features, raw = display_scaling_steps._gsettings_get_features()

    assert features == []
    assert raw == ""


def test_gsettings_set_sources_remote_session_environment():
    with (
        patch.object(display_scaling_steps, "_IN_CONTAINER", True),
        patch.object(
            display_scaling_steps, "_run_host", return_value=("", 0, "")
        ) as run_host,
    ):
        display_scaling_steps._gsettings_set_features("['feature']")

    run_host.assert_called_once_with(
        "source /tmp/session.env 2>/dev/null; "
        "gsettings set org.gnome.mutter experimental-features "
        "'['\"'\"'feature'\"'\"']'"
    )


def test_scale_assertion_checks_every_logical_monitor():
    context = SimpleNamespace(display_scale_target=1.5)
    with patch.object(
        display_scaling_steps, "_get_display_scales", return_value=[1.5, 1.5]
    ):
        display_scaling_steps.current_display_scale_matches_applied(context)


def test_scale_assertion_reports_mismatched_monitor():
    context = SimpleNamespace(display_scale_target=1.5)
    with patch.object(
        display_scaling_steps, "_get_display_scales", return_value=[1.5, 1.25]
    ):
        with pytest.raises(AssertionError, match="Expected scale 1.5"):
            display_scaling_steps.current_display_scale_matches_applied(context)
