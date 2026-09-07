"""Unit tests for power_status_color_steps.py pure helper functions."""
import sys
import types
from unittest.mock import MagicMock, patch


def _import_power_status_color_steps(in_container: bool = False):
    """Import the module with controlled side effects."""
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    for key in list(sys.modules):
        if "power_status_color_steps" in key:
            del sys.modules[key]

    with patch("os.path.lexists", return_value=in_container), \
         patch("os.path.isfile", return_value=not in_container):
        import tests.smoke.features.steps.power_status_color_steps as m  # noqa: PLC0415
    return m


class TestConstants:
    def test_uuid(self):
        m = _import_power_status_color_steps()
        assert m.POWER_STATUS_UUID == "power-status-color@projectbluefin.io"

    def test_style_classes(self):
        m = _import_power_status_color_steps()
        assert m.CLASS_OVERDUE == "power-status-overdue"
        assert m.CLASS_REBOOT == "power-status-reboot"

    def test_reboot_flag_file(self):
        m = _import_power_status_color_steps()
        assert m.REBOOT_FLAG_FILE == "/run/reboot-required"


class TestRunHost:
    def test_direct_run_when_not_in_container(self):
        m = _import_power_status_color_steps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="hi", returncode=0, stderr="")
            stdout, rc, _ = m._run_host(["echo", "hi"])
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["echo", "hi"]
        assert stdout == "hi"
        assert rc == 0

    def test_ssh_wrapper_used_in_container(self):
        m = _import_power_status_color_steps(in_container=True)
        m._IN_CONTAINER = True
        with patch("subprocess.run") as mock_run, \
             patch.dict("os.environ", {"VM_IP": "10.0.0.5"}):
            mock_run.return_value = MagicMock(stdout="", returncode=0, stderr="")
            m._run_host(["uptime"])
        args = mock_run.call_args[0][0]
        assert "ssh" in args[0]
        assert "10.0.0.5" in " ".join(args)


class TestRunAdmin:
    def test_uses_sudo_first_and_returns_on_success(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_run_host") as mock_run_host:
            mock_run_host.return_value = ("", 0, "")
            out, rc, err = m._run_admin("touch /run/reboot-required")
        first_call_cmd = mock_run_host.call_args_list[0][0][0]
        assert first_call_cmd.startswith("sudo -n")
        assert rc == 0
        mock_run_host.assert_called_once()

    def test_falls_back_without_sudo_on_unauthorized(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_run_host") as mock_run_host:
            mock_run_host.side_effect = [
                ("", 1, "sudo: sorry, user is not allowed to execute (unauthorized)"),
                ("", 0, ""),
            ]
            out, rc, err = m._run_admin("touch /run/reboot-required")
        assert mock_run_host.call_count == 2
        second_call_cmd = mock_run_host.call_args_list[1][0][0]
        assert second_call_cmd == "touch /run/reboot-required"
        assert rc == 0

    def test_stops_retry_on_other_errors(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_run_host") as mock_run_host:
            mock_run_host.return_value = ("", 1, "no such file or directory")
            out, rc, err = m._run_admin("touch /bad/path")
        mock_run_host.assert_called_once()
        assert rc == 1


class TestShellEval:
    def test_prepends_unsafe_mode(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_run_host") as mock_run_host:
            mock_run_host.return_value = ("(true, 'ok')", 0, "")
            m._shell_eval("Main.overview.hide()")
        js_arg = mock_run_host.call_args[0][0][-1]
        assert "global.context.unsafe_mode = true;" in js_arg
        assert "Main.overview.hide()" in js_arg

    def test_raises_on_nonzero_returncode(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_run_host") as mock_run_host:
            mock_run_host.return_value = ("", 1, "boom")
            try:
                m._shell_eval("1+1")
                assert False, "expected AssertionError"
            except AssertionError as exc:
                assert "boom" in str(exc)


class TestEvalBool:
    def test_parses_true(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_shell_eval", return_value="(true, 'true')"):
            assert m._eval_bool("x") is True

    def test_parses_false(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_shell_eval", return_value="(true, 'false')"):
            assert m._eval_bool("x") is False

    def test_parses_double_quoted_variant(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_shell_eval", return_value='(true, \'"true"\')'):
            assert m._eval_bool("x") is True

    def test_raises_when_unparseable(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_shell_eval", return_value="garbage output"):
            try:
                m._eval_bool("x")
                assert False, "expected AssertionError"
            except AssertionError:
                pass


class TestHasStyleClass:
    def test_queries_power_button_via_shell_eval(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_eval_bool", return_value=True) as mock_eval_bool:
            result = m._has_style_class("power-status-reboot")
        assert result is True
        js = mock_eval_bool.call_args[0][0]
        assert "power-status-reboot" in js
        assert "has_style_class_name" in js


class TestWaitForStyleClass:
    def test_returns_true_immediately_when_matched(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_has_style_class", return_value=True):
            assert m._wait_for_style_class("power-status-reboot", True, 5) is True

    def test_returns_false_after_timeout(self):
        m = _import_power_status_color_steps()
        with patch.object(m, "_has_style_class", return_value=False), \
             patch("time.sleep", return_value=None):
            assert m._wait_for_style_class("power-status-reboot", True, 0) is False

    def test_tolerates_transient_assertion_errors(self):
        m = _import_power_status_color_steps()
        calls = {"n": 0}

        def flaky(_class_name):
            calls["n"] += 1
            if calls["n"] < 2:
                raise AssertionError("Shell.Eval failed")
            return True

        with patch.object(m, "_has_style_class", side_effect=flaky), \
             patch("time.sleep", return_value=None):
            assert m._wait_for_style_class("power-status-reboot", True, 5) is True


class TestExtensionStubJs:
    def test_wraps_body_with_lookup(self):
        m = _import_power_status_color_steps()
        js = m._extension_stub_js("ext._checkStatus();")
        assert m.POWER_STATUS_UUID in js
        assert "stateObj" in js
        assert "ext._checkStatus();" in js
        assert "no-ext" in js
