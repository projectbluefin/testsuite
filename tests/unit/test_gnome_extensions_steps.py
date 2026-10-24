"""Unit tests for gnome_extensions_steps.py pure helper functions."""
import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_gnome_extensions_steps(in_container: bool = False, tree_available: bool = True):
    """Import the module with controlled side effects."""
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

    # Remove cached module
    for key in list(sys.modules):
        if "gnome_extensions_steps" in key:
            del sys.modules[key]

    with patch("os.path.lexists", return_value=in_container), \
         patch("os.path.isfile", return_value=not in_container):
        import tests.smoke.features.steps.gnome_extensions_steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestExtensionsConstants:
    def test_extensions_app_names_is_tuple(self):
        m = _import_gnome_extensions_steps()
        assert isinstance(m.EXTENSIONS_APP_NAMES, tuple)
        assert len(m.EXTENSIONS_APP_NAMES) >= 3

    def test_extensions_app_names_contains_org_gnome(self):
        m = _import_gnome_extensions_steps()
        assert "org.gnome.Extensions" in m.EXTENSIONS_APP_NAMES

    def test_extensions_window_roles_is_set(self):
        m = _import_gnome_extensions_steps()
        assert isinstance(m.EXTENSIONS_WINDOW_ROLES, set)
        assert "frame" in m.EXTENSIONS_WINDOW_ROLES

    def test_extensions_desktop_file_path(self):
        m = _import_gnome_extensions_steps()
        assert m.EXTENSIONS_DESKTOP_FILE.endswith(".desktop")
        assert "org.gnome.Extensions" in m.EXTENSIONS_DESKTOP_FILE


# ---------------------------------------------------------------------------
# _skip_if_no_atspi
# ---------------------------------------------------------------------------

class TestSkipIfNoAtspi:
    def test_returns_false_when_tree_available(self):
        m = _import_gnome_extensions_steps(tree_available=True)
        context = MagicMock()
        result = m._skip_if_no_atspi(context)
        assert result is False

    def test_returns_true_when_tree_is_none(self):
        m = _import_gnome_extensions_steps(tree_available=False)
        m.tree = None  # force tree to None (as module does when import fails)
        context = MagicMock()
        result = m._skip_if_no_atspi(context)
        assert result is True

    def test_calls_scenario_skip_when_tree_none(self):
        m = _import_gnome_extensions_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        context.scenario.skip.assert_called_once()
        assert "AT-SPI" in context.scenario.skip.call_args[0][0]

    def test_tolerates_skip_exception(self):
        m = _import_gnome_extensions_steps(tree_available=False)
        m.tree = None
        context = MagicMock()
        context.scenario.skip.side_effect = RuntimeError("no scenario")
        # Should not raise
        result = m._skip_if_no_atspi(context)
        assert result is True


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------

class TestRun:
    def test_returns_stdout_rc_stderr_tuple(self):
        m = _import_gnome_extensions_steps()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="hello\n", returncode=0, stderr="")
            stdout, rc, stderr = m._run(["echo", "hello"])
        assert stdout == "hello"
        assert rc == 0
        assert stderr == ""

    def test_strips_trailing_newline(self):
        m = _import_gnome_extensions_steps()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="output\n\n", returncode=0, stderr="warn\n")
            stdout, rc, stderr = m._run(["cmd"])
        assert stdout == "output"
        assert stderr == "warn"

    def test_non_zero_rc_propagated(self):
        m = _import_gnome_extensions_steps()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=1, stderr="error msg")
            _, rc, stderr = m._run(["false"])
        assert rc == 1
        assert stderr == "error msg"

    def test_passes_check_false_to_subprocess(self):
        m = _import_gnome_extensions_steps()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0, stderr="")
            m._run(["cmd"])
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["check"] is False


# ---------------------------------------------------------------------------
# _run_host
# ---------------------------------------------------------------------------

class TestRunHost:
    def test_direct_run_when_not_in_container_list(self):
        m = _import_gnome_extensions_steps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="result", returncode=0, stderr="")
            stdout, rc, _ = m._run_host(["echo", "hi"])
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["echo", "hi"]
        assert stdout == "result"

    def test_direct_run_when_not_in_container_string(self):
        m = _import_gnome_extensions_steps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="out", returncode=0, stderr="")
            m._run_host("echo hi")
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("shell") is True

    def test_ssh_wrapper_used_in_container(self):
        m = _import_gnome_extensions_steps(in_container=True)
        m._IN_CONTAINER = True
        with patch("subprocess.run") as mock_run, \
             patch.dict("os.environ", {"VM_IP": "10.0.0.1", "SSH_PORT": "2222", "VM_USER": "testuser"}):
            mock_run.return_value = MagicMock(stdout="out", returncode=0, stderr="")
            m._run_host(["uptime"])
        args = mock_run.call_args[0][0]
        assert "ssh" in args[0]
        assert "10.0.0.1" in " ".join(args)
        assert "2222" in args

    def test_ssh_list_cmd_is_shell_quoted(self):
        m = _import_gnome_extensions_steps(in_container=True)
        m._IN_CONTAINER = True
        with patch("subprocess.run") as mock_run, \
             patch.dict("os.environ", {"VM_IP": "127.0.0.1"}):
            mock_run.return_value = MagicMock(stdout="", returncode=0, stderr="")
            m._run_host(["echo", "hello world"])
        args = mock_run.call_args[0][0]
        # The last element is the shell-quoted command string
        cmd_str = args[-1]
        assert "hello world" in cmd_str


class TestExtensionListSteps:
    def test_at_least_one_gnome_extension_is_installed_fallback_to_dbus(self):
        m = _import_gnome_extensions_steps()
        context = MagicMock()

        def fake_run_host(cmd):
            if isinstance(cmd, list) and "list" in cmd:
                return ("", 2, "portal timeout")
            if isinstance(cmd, str) and "ListExtensions" in cmd:
                return ("({'dash-to-dock@micxgx.gmail.com': {'state': <1.0>}},)", 0, "")
            return ("", 1, "error")

        with patch.object(m, "_run_host", side_effect=fake_run_host):
            m.at_least_one_gnome_extension_is_installed(context)
            assert "dash-to-dock@micxgx.gmail.com" in context.installed_extensions

    def test_at_least_one_gnome_extension_is_enabled_fallback_to_dbus(self):
        m = _import_gnome_extensions_steps()
        context = MagicMock()

        def fake_run_host(cmd):
            if isinstance(cmd, list) and "list" in cmd:
                return ("", 2, "portal timeout")
            if isinstance(cmd, str) and "ListExtensions" in cmd:
                return ("({'dash-to-dock@micxgx.gmail.com': {'state': <1.0>}},)", 0, "")
            return ("", 1, "error")

        with patch.object(m, "_run_host", side_effect=fake_run_host):
            m.at_least_one_gnome_extension_is_enabled(context)
            assert "dash-to-dock@micxgx.gmail.com" in context.enabled_extensions


class TestExtensionInstalledOrSkip:
    UUID = "search-light@icedman.github.com"

    def _run(self, installed: bool, major):
        m = _import_gnome_extensions_steps()
        context = MagicMock()
        with patch.object(m, "_extension_installed", return_value=installed), \
             patch.object(m, "_gnome_shell_major_version", return_value=major):
            m.gnome_extension_installed_or_skip(context, self.UUID, 51)
        return context

    def test_installed_passes_without_skip(self):
        context = self._run(installed=True, major=50)
        context.scenario.skip.assert_not_called()

    def test_missing_on_gnome_51_skips(self):
        context = self._run(installed=False, major=51)
        context.scenario.skip.assert_called_once()

    def test_missing_on_newer_gnome_skips(self):
        context = self._run(installed=False, major=52)
        context.scenario.skip.assert_called_once()

    def test_missing_on_older_gnome_fails(self):
        import pytest  # noqa: PLC0415
        with pytest.raises(AssertionError, match="GNOME 50"):
            self._run(installed=False, major=50)

    def test_missing_with_unknown_version_fails(self):
        import pytest  # noqa: PLC0415
        with pytest.raises(AssertionError, match="unknown GNOME version"):
            self._run(installed=False, major=None)


class TestGnomeShellMajorVersion:
    def test_parses_gnome_shell_version(self):
        m = _import_gnome_extensions_steps()
        with patch.object(m, "_run_host", return_value=("GNOME Shell 51.1", 0, "")):
            assert m._gnome_shell_major_version() == 51

    def test_returns_none_on_failure(self):
        m = _import_gnome_extensions_steps()
        with patch.object(m, "_run_host", return_value=("", 1, "nope")):
            assert m._gnome_shell_major_version() is None
