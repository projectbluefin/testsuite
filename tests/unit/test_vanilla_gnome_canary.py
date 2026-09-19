"""Unit tests for the GNOME Shell version canary step in vanilla-gnome."""
import sys
import types
from unittest.mock import MagicMock, patch


def _import_vanilla_gnome_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub
    sys.modules["behave.runner"] = MagicMock()

    dogtail_stub = types.ModuleType("dogtail")
    dogtail_tree_stub = types.ModuleType("dogtail.tree")
    dogtail_tree_stub.root = MagicMock()
    dogtail_pred_stub = types.ModuleType("dogtail.predicate")
    dogtail_pred_stub.GenericPredicate = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = dogtail_tree_stub
    sys.modules["dogtail.predicate"] = dogtail_pred_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    for key in list(sys.modules):
        if "vanilla-gnome.features.steps.steps" in key or \
           "vanilla_gnome_steps" in key:
            del sys.modules[key]

    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "vanilla_gnome_steps_canary",
        os.path.join(
            os.path.dirname(__file__),
            "..", "vanilla-gnome", "features", "steps", "steps.py"
        ),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestReportShellVersion:
    def test_in_container_success(self, capsys):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="'51.0'\n", stderr="")
        with patch.object(m, "_IN_CONTAINER", True), \
             patch.object(m, "_ssh_run", return_value=mock_result) as mock_ssh:
            m.report_shell_version(MagicMock())
            mock_ssh.assert_called_once()
            captured = capsys.readouterr()
            assert "GNOME Shell ShellVersion: '51.0'" in captured.out

    def test_in_container_failure_warns_never_raises(self, capsys):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=1, stdout="", stderr="org.freedesktop.DBus.Error.ServiceUnknown")
        with patch.object(m, "_IN_CONTAINER", True), \
             patch.object(m, "_ssh_run", return_value=mock_result):
            # Must not raise
            m.report_shell_version(MagicMock())
            captured = capsys.readouterr()
            assert "WARNING: gdbus via SSH returned 1" in captured.out

    def test_in_container_exception_warns_never_raises(self, capsys):
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_IN_CONTAINER", True), \
             patch.object(m, "_ssh_run", side_effect=Exception("SSH connection failed")):
            # Must not raise
            m.report_shell_version(MagicMock())
            captured = capsys.readouterr()
            assert "WARNING: could not read ShellVersion: SSH connection failed" in captured.out

    def test_outside_container_success(self, capsys):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="'50.0'\n", stderr="")
        with patch.object(m, "_IN_CONTAINER", False), \
             patch("subprocess.run", return_value=mock_result) as mock_subproc:
            m.report_shell_version(MagicMock())
            mock_subproc.assert_called_once()
            captured = capsys.readouterr()
            assert "GNOME Shell ShellVersion: '50.0'" in captured.out

    def test_outside_container_failure_warns_never_raises(self, capsys):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=1, stdout="", stderr="dbus error")
        with patch.object(m, "_IN_CONTAINER", False), \
             patch("subprocess.run", return_value=mock_result):
            # Must not raise
            m.report_shell_version(MagicMock())
            captured = capsys.readouterr()
            assert "WARNING: gdbus returned 1" in captured.out

    def test_empty_version_reports_unreadable(self, capsys):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(m, "_IN_CONTAINER", False), \
             patch("subprocess.run", return_value=mock_result):
            m.report_shell_version(MagicMock())
            captured = capsys.readouterr()
            assert "GNOME Shell ShellVersion: <unreadable>" in captured.out
