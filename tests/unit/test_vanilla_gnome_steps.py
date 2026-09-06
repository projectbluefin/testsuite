"""Unit tests for tests/vanilla-gnome/features/steps/steps.py helpers."""
import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

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
           "vanilla_gnome.features.steps.steps" in key or \
           "tests.shared.gnome_shell_steps" in key:
            del sys.modules[key]

    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "vanilla_gnome_steps",
        os.path.join(
            os.path.dirname(__file__),
            "..", "vanilla-gnome", "features", "steps", "steps.py"
        ),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _command_exists
# ---------------------------------------------------------------------------

class TestCommandExists:
    def test_returns_true_when_ssh_command_found(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="/usr/bin/gnome-files\n")
        with patch.object(m, "_ssh_run", return_value=mock_result):
            assert m._command_exists("gnome-files") is True

    def test_returns_false_when_ssh_command_not_found(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=1, stdout="")
        with patch.object(m, "_ssh_run", return_value=mock_result):
            assert m._command_exists("nonexistent") is False

    def test_returns_false_when_ssh_not_available(self):
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_ssh_run", side_effect=FileNotFoundError):
            assert m._command_exists("anything") is False


# ---------------------------------------------------------------------------
# _flatpak_app_exists
# ---------------------------------------------------------------------------

class TestFlatpakAppExists:
    def test_returns_true_when_app_in_list(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="org.gnome.Nautilus\n")
        with patch.object(m, "_ssh_run", return_value=mock_result):
            assert m._flatpak_app_exists("org.gnome.Nautilus") is True

    def test_returns_false_when_app_not_in_list(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="org.gnome.Calculator\n")
        with patch.object(m, "_ssh_run", return_value=mock_result):
            assert m._flatpak_app_exists("org.gnome.Nautilus") is False

    def test_returns_false_when_ssh_not_available(self):
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_ssh_run", side_effect=FileNotFoundError):
            assert m._flatpak_app_exists("org.gnome.Nautilus") is False


# ---------------------------------------------------------------------------
# _assert_any_app_present
# ---------------------------------------------------------------------------

class TestAssertAnyAppPresent:
    def test_passes_when_command_found(self):
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_command_exists", return_value=True), \
             patch.object(m, "_flatpak_app_exists", return_value=False):
            m._assert_any_app_present("Test app", ("myapp",), ("org.test.App",))

    def test_passes_when_flatpak_found(self):
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_command_exists", return_value=False), \
             patch.object(m, "_flatpak_app_exists", return_value=True):
            m._assert_any_app_present("Test app", ("myapp",), ("org.test.App",))

    def test_raises_when_neither_found(self):
        import pytest
        m = _import_vanilla_gnome_steps()
        with patch.object(m, "_command_exists", return_value=False), \
             patch.object(m, "_flatpak_app_exists", return_value=False):
            with pytest.raises(AssertionError, match="Test app not found"):
                m._assert_any_app_present("Test app", ("myapp",), ("org.test.App",))

    def test_gnome_files_checks_gnome_files_and_nautilus(self):
        """PR #388: gnome-files added as fallback alongside nautilus."""
        m = _import_vanilla_gnome_steps()
        checked_commands = []
        def track_cmd(cmd, context=None):
            checked_commands.append(cmd)
            return cmd == "gnome-files"
        with patch.object(m, "_command_exists", side_effect=track_cmd), \
             patch.object(m, "_flatpak_app_exists", return_value=False):
            ctx = MagicMock()
            m.files_application_is_installed(ctx)
        assert "gnome-files" in checked_commands
        assert "nautilus" in checked_commands


# ---------------------------------------------------------------------------
# no_coredump_entries_exist
# ---------------------------------------------------------------------------

class TestNoCoredumpEntriesExist:
    def test_skips_gracefully_when_coredumpctl_not_found(self):
        """PR #388: FileNotFoundError means no coredumps possible — skip gracefully."""
        m = _import_vanilla_gnome_steps()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            # Should not raise
            m.no_coredump_entries_exist(MagicMock(), "gnome-shell")

    def test_passes_when_no_entries(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=1, stdout="No entries", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            m.no_coredump_entries_exist(MagicMock(), "gnome-shell")

    def test_passes_when_coredumpctl_succeeds_with_no_match(self):
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            m.no_coredump_entries_exist(MagicMock(), "gnome-shell")

    def test_raises_when_coredump_entry_found(self):
        import pytest
        m = _import_vanilla_gnome_steps()
        output = "Thu 2026-01-01 12:00:00 UTC gnome-shell 12345 SIGABRT"
        mock_result = MagicMock(returncode=0, stdout=output, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(AssertionError, match="Unexpected coredump"):
                m.no_coredump_entries_exist(MagicMock(), "gnome-shell")

    def test_raises_on_unexpected_returncode(self):
        import pytest
        m = _import_vanilla_gnome_steps()
        mock_result = MagicMock(returncode=2, stdout="error", stderr="something bad")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(AssertionError, match="coredumpctl list failed"):
                m.no_coredump_entries_exist(MagicMock(), "gnome-shell")
