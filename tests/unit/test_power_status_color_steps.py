"""Unit tests for power_status_color_steps.py pure helpers.

The module drives Shell.Eval / SSH (not unit-testable), so we stub the shared
modules it imports (``steps.steps._run_host``, ``steps.gnome_extensions_steps
._extension_state``, ``tests.shared.gnome_shell_steps._eval_bool``) and assert
the pure logic: constants, the Shell.Eval JS probe, file creation/removal and
extension enable/disable command construction, and the class polling loop.
"""
import sys
import types
from unittest.mock import MagicMock, patch


class _FakeContext:
    """Minimal behave context stand-in (steps ignore it)."""


def _import_module():
    """Import power_status_color_steps with its GNOME deps stubbed."""
    # behave
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    # steps package (stub both _run_host and _extension_state)
    steps_pkg = types.ModuleType("steps")
    steps_pkg.__path__ = []
    sys.modules["steps"] = steps_pkg
    steps_stub = types.ModuleType("steps.steps")
    steps_stub._run_host = MagicMock(return_value=("", 0, ""))
    sys.modules["steps.steps"] = steps_stub
    gext_stub = types.ModuleType("steps.gnome_extensions_steps")
    gext_stub._extension_state = MagicMock(return_value="2")
    sys.modules["steps.gnome_extensions_steps"] = gext_stub

    # tests.shared.gnome_shell_steps
    if "tests.shared" in sys.modules and not hasattr(sys.modules["tests.shared"], "__path__"):
        del sys.modules["tests.shared"]
    gss_stub = types.ModuleType("tests.shared.gnome_shell_steps")
    gss_stub._eval_bool = MagicMock(return_value=True)
    sys.modules["tests.shared.gnome_shell_steps"] = gss_stub

    for key in list(sys.modules):
        if "power_status_color_steps" in key:
            del sys.modules[key]

    import tests.smoke.features.steps.power_status_color_steps as m  # noqa: PLC0415
    return m


class TestConstants:
    def test_class_names_match_extension(self):
        m = _import_module()
        assert m.CLASS_REBOOT == "power-status-reboot"
        assert m.CLASS_OVERDUE == "power-status-overdue"

    def test_alert_classes_tuple(self):
        m = _import_module()
        assert m.POWER_ALERT_CLASSES == ("power-status-reboot", "power-status-overdue")

    def test_reboot_flag_file(self):
        m = _import_module()
        assert m.REBOOT_FLAG_FILE == "/run/reboot-required"


class TestPowerButtonClassJs:
    def test_probe_targets_the_requested_class(self):
        m = _import_module()
        js = m._power_button_class_js("power-status-reboot")
        assert "has_style_class_name('power-status-reboot')" in js
        assert "quickSettings" in js
        assert js.rstrip().endswith(")()")

    def test_probe_returns_false_when_button_absent(self):
        m = _import_module()
        js = m._power_button_class_js("power-status-overdue")
        assert "if(!btn)return 'false';" in js


class TestFileSteps:
    def test_create_runs_sudo_touch(self):
        m = _import_module()
        with patch.object(m, "_run_host") as run:
            m.file_is_created(_FakeContext(), "/run/reboot-required")
        run.assert_called_once_with("sudo touch /run/reboot-required")

    def test_remove_runs_sudo_rm(self):
        m = _import_module()
        with patch.object(m, "_run_host") as run:
            m.file_is_removed(_FakeContext(), "/run/reboot-required")
        run.assert_called_once_with("sudo rm -f /run/reboot-required")


class TestDisableEnable:
    def test_disable_sources_session_env_and_disable_uuid(self):
        m = _import_module()
        with patch.object(m, "_run_host") as run, \
             patch.object(m, "_extension_state", side_effect=["8", "1", "2"]):
            m.gnome_extension_is_disabled(_FakeContext(), "power-status-color@projectbluefin.io")
        run.assert_called_once_with(
            "source /tmp/session.env 2>/dev/null; "
            "gnome-extensions disable power-status-color@projectbluefin.io"
        )

    def test_enable_again_sources_session_env_and_enable_uuid(self):
        m = _import_module()
        with patch.object(m, "_run_host") as run, \
             patch.object(m, "_extension_state", side_effect=["6", "1"]):
            m.gnome_extension_is_enabled_again(_FakeContext(), "power-status-color@projectbluefin.io")
        run.assert_called_once_with(
            "source /tmp/session.env 2>/dev/null; "
            "gnome-extensions enable power-status-color@projectbluefin.io"
        )


class TestPolling:
    def test_wait_present_returns_when_class_appears(self):
        m = _import_module()
        with patch.object(m, "_power_button_has_class", return_value=True):
            m._wait_power_button_class("power-status-reboot", present=True, timeout=2)
        # no exception => success

    def test_wait_absent_returns_when_class_gone(self):
        m = _import_module()
        with patch.object(m, "_power_button_has_class", return_value=False):
            m._wait_power_button_class("power-status-reboot", present=False, timeout=2)
        # no exception => success

    def test_wait_present_raises_on_timeout(self):
        m = _import_module()
        with patch.object(m, "_power_button_has_class", return_value=False):
            try:
                m._wait_power_button_class("power-status-reboot", present=True, timeout=0.2)
            except AssertionError as exc:
                assert "power-status-reboot" in str(exc)
            else:
                raise AssertionError("expected AssertionError on timeout")

    def test_has_no_alert_classes_returns_when_both_absent(self):
        m = _import_module()
        with patch.object(m, "_power_button_has_class", return_value=False):
            m.power_button_has_no_alert_classes(_FakeContext())
        # no exception => success