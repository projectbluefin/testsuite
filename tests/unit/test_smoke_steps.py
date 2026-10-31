"""Unit tests for tests/smoke/features/steps/steps.py pure helper functions.

Tests focus on:
- _eval_bool(): gdbus output parsing, GNOME 50 double-quote variant
- _gsettings_get_bool(): true/false parsing and edge cases
- _wait_eval_bool(): polling logic / early exit
- _IN_CONTAINER: detection constant
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub helper
# ---------------------------------------------------------------------------

def _import_steps(in_container: bool = False):
    """Import steps.py with all GNOME dependencies stubbed out."""
    # Stub behave
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    # Stub dogtail
    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    # Stub qecore
    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    # Stub app_support
    app_support_stub = types.ModuleType("app_support")
    sys.modules["app_support"] = app_support_stub

    # Stub shared gnome_shell_steps (star-imported)
    if "tests.shared" in sys.modules and not hasattr(sys.modules["tests.shared"], "__path__"):
        del sys.modules["tests.shared"]
    gnome_shell_stub = types.ModuleType("tests.shared.gnome_shell_steps")
    sys.modules["tests.shared.gnome_shell_steps"] = gnome_shell_stub

    # Evict the module so it reimports fresh
    for key in list(sys.modules):
        if "smoke.features.steps.steps" in key or key.endswith("smoke_steps"):
            del sys.modules[key]

    with patch.dict(os.environ, {}, clear=False):
        with patch("os.path.lexists", return_value=in_container), \
             patch("os.path.isfile", return_value=not in_container):
            import tests.smoke.features.steps.steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# _IN_CONTAINER
# ---------------------------------------------------------------------------

class TestInContainer:
    def test_false_outside_container(self):
        m = _import_steps(in_container=False)
        assert m._IN_CONTAINER is False

    def test_true_inside_container(self):
        m = _import_steps(in_container=True)
        assert m._IN_CONTAINER is True


# ---------------------------------------------------------------------------
# _eval_bool — gdbus output parsing
# ---------------------------------------------------------------------------

class TestEvalBool:
    def test_returns_true_from_standard_format(self):
        m = _import_steps()
        with patch.object(m, "_shell_eval", return_value="(true, 'true')"):
            assert m._eval_bool("someJs") is True

    def test_returns_false_from_standard_format(self):
        m = _import_steps()
        with patch.object(m, "_shell_eval", return_value="(true, 'false')"):
            assert m._eval_bool("someJs") is False

    def test_returns_true_from_gnome50_double_quote_format(self):
        # GNOME 50 wraps result in extra double-quotes: (true, '"true"')
        m = _import_steps()
        with patch.object(m, "_shell_eval", return_value="(true, '\"true\"')"):
            assert m._eval_bool("someJs") is True

    def test_returns_false_from_gnome50_double_quote_format(self):
        m = _import_steps()
        with patch.object(m, "_shell_eval", return_value="(true, '\"false\"')"):
            assert m._eval_bool("someJs") is False

    def test_raises_on_non_boolean_output(self):
        m = _import_steps()
        import pytest
        with patch.object(m, "_shell_eval", return_value="(true, '42')"):
            with pytest.raises(AssertionError, match="boolean"):
                m._eval_bool("someJs")

    def test_raises_on_empty_output(self):
        m = _import_steps()
        import pytest
        with patch.object(m, "_shell_eval", return_value=""):
            with pytest.raises(AssertionError):
                m._eval_bool("someJs")

    def test_case_insensitive_true(self):
        m = _import_steps()
        with patch.object(m, "_shell_eval", return_value="(true, 'TRUE')"):
            assert m._eval_bool("someJs") is True


# ---------------------------------------------------------------------------
# _gsettings_get_bool
# ---------------------------------------------------------------------------

class TestGsettingsGetBool:
    def test_returns_true(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=("true", 0, "")):
            assert m._gsettings_get_bool("org.gnome.x", "key") is True

    def test_returns_false(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=("false", 0, "")):
            assert m._gsettings_get_bool("org.gnome.x", "key") is False

    def test_raises_on_rc_nonzero(self):
        m = _import_steps()
        import pytest
        with patch.object(m, "_run_host", return_value=("", 1, "schema not found")):
            with pytest.raises(AssertionError, match="failed"):
                m._gsettings_get_bool("org.gnome.x", "key")

    def test_raises_on_unexpected_value(self):
        m = _import_steps()
        import pytest
        with patch.object(m, "_run_host", return_value=("maybe", 0, "")):
            with pytest.raises(AssertionError, match="Unexpected"):
                m._gsettings_get_bool("org.gnome.x", "key")

    def test_strips_whitespace_from_value(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=("  true  ", 0, "")):
            assert m._gsettings_get_bool("org.gnome.x", "key") is True


# ---------------------------------------------------------------------------
# _wait_eval_bool
# ---------------------------------------------------------------------------

class TestWaitEvalBool:
    def test_returns_true_immediately(self):
        m = _import_steps()
        with patch.object(m, "_eval_bool", return_value=True), \
             patch("time.sleep"):
            result = m._wait_eval_bool("someJs", expected=True, retries=3, delay=0.0)
        assert result is True

    def test_returns_false_on_timeout(self):
        m = _import_steps()
        with patch.object(m, "_eval_bool", return_value=False), \
             patch("time.sleep"):
            result = m._wait_eval_bool("someJs", expected=True, retries=3, delay=0.0)
        assert result is False

    def test_retries_on_assertion_error(self):
        m = _import_steps()
        call_count = [0]

        def flaky_eval(js):
            call_count[0] += 1
            if call_count[0] < 3:
                raise AssertionError("not ready")
            return True

        with patch.object(m, "_eval_bool", side_effect=flaky_eval), \
             patch("time.sleep"):
            result = m._wait_eval_bool("someJs", expected=True, retries=5, delay=0.0)
        assert result is True
        assert call_count[0] == 3

    def test_returns_false_when_expected_false_and_always_true(self):
        m = _import_steps()
        with patch.object(m, "_eval_bool", return_value=True), \
             patch("time.sleep"):
            result = m._wait_eval_bool("someJs", expected=False, retries=3, delay=0.0)
        assert result is False


class TestWelcomeDialog:
    def test_retries_until_skip_button_appears_and_clicks_it(self):
        m = _import_steps()
        skip = MagicMock()
        tree = sys.modules["dogtail.tree"]
        tree.root.findChildren.side_effect = [[], [skip]]

        with patch.object(m, "sleep") as sleep:
            assert m._dismiss_welcome_dialog(attempts=2, delay=0.1) is True

        sleep.assert_called_once_with(0.1)
        skip.click.assert_called_once_with()

    def test_returns_false_when_dialog_never_appears(self):
        m = _import_steps()
        tree = sys.modules["dogtail.tree"]
        tree.root.findChildren.return_value = []

        with patch.object(m, "sleep"):
            assert m._dismiss_welcome_dialog(attempts=2, delay=0) is False


class TestDashToDock:
    def test_requires_enabled_extension_and_visible_actor(self):
        m = _import_steps()
        extension_info = "({'state': <uint32 1>},)"

        with patch.object(m, "_gdbus_call", return_value=extension_info), \
             patch.object(m, "_wait_eval_bool", return_value=True) as wait_visible:
            m.dash_to_dock_visible(MagicMock())

        visibility_js = wait_visible.call_args.args[0]
        assert "dashtodockContainer" in visibility_js
        assert "is_mapped()" in visibility_js
        assert "get_transformed_size()" in visibility_js

    def test_fails_when_enabled_extension_is_not_visibly_rendered(self):
        import pytest

        m = _import_steps()
        extension_info = "({'state': <uint32 1>},)"
        with patch.object(m, "_gdbus_call", return_value=extension_info), \
             patch.object(m, "_wait_eval_bool", return_value=False), \
             pytest.raises(AssertionError, match="not visibly rendered"):
            m.dash_to_dock_visible(MagicMock())

# ---------------------------------------------------------------------------
# DND helpers
# ---------------------------------------------------------------------------

class TestDoNotDisturbHelpers:
    def test_dnd_toggle_js_checks_all_known_property_names(self):
        m = _import_steps()
        assert "_doNotDisturb" in m._DND_TOGGLE_JS
        assert "_do_not_disturb" in m._DND_TOGGLE_JS
        assert "_dnd" in m._DND_TOGGLE_JS

    def test_set_dnd_enabled_toggles_when_alias_exists_and_state_differs(self):
        m = _import_steps()
        with patch.object(m, "_eval_bool", side_effect=[True, False]), \
             patch.object(m, "_wait_eval_bool", return_value=True), \
             patch.object(m, "_shell_eval") as shell_eval:
            m._set_dnd_enabled(True)
        shell_eval.assert_called_once_with(m._dnd_toggle_toggle_js())

    def test_set_dnd_enabled_falls_back_to_gsettings_when_toggle_missing(self):
        m = _import_steps()
        with patch.object(m, "_eval_bool", side_effect=AssertionError("missing")), \
             patch.object(m, "_gsettings_set_bool") as set_bool, \
             patch.object(m, "_gsettings_get_bool", return_value=False):
            m._set_dnd_enabled(True)
        set_bool.assert_called_once_with(
            "org.gnome.desktop.notifications",
            "show-banners",
            False,
        )


# ---------------------------------------------------------------------------
# _run_host — routing logic (container vs. direct)
# ---------------------------------------------------------------------------

class TestRunHost:
    def test_run_host_creates_session_env_when_missing(self):
        m = _import_steps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", returncode=0, stderr="")
            stdout, rc, stderr = m._run_host("echo test")
            assert rc == 0
            _, kwargs = mock_run.call_args
            assert kwargs.get("executable") == "/bin/bash"

    def test_uses_ssh_when_in_container(self):
        m = _import_steps(in_container=True)
        m._IN_CONTAINER = True
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="output\n", returncode=0, stderr="")
            stdout, rc, stderr = m._run_host("echo hi")
        call_args = mock_run.call_args[0][0]
        assert "ssh" in call_args[0]

    def test_uses_shell_when_not_in_container(self):
        m = _import_steps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="output\n", returncode=0, stderr="")
            stdout, rc, stderr = m._run_host("echo hi")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("shell") is True

    def test_returns_stripped_stdout(self):
        m = _import_steps()
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="hello world\n", returncode=0, stderr="")
            stdout, rc, _ = m._run_host("echo hi")
        assert stdout == "hello world"
        assert rc == 0


class TestFlatpakFilesystems:
    PERMS = (
        "[Context]\nshared=ipc;\nfilesystems=xdg-run/gvfsd;host;host-os:ro;~/.var/app;\n\n"
        "[Session Bus Policy]\norg.gtk.vfs.*=talk\n"
    )

    def test_parses_every_value_not_just_first(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=(self.PERMS, 0, "")):
            assert m._flatpak_filesystems("x") == {"xdg-run/gvfsd", "host", "host-os:ro", "~/.var/app"}

    def test_no_filesystems_key_is_empty(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=("[Context]\nshared=ipc;\n", 0, "")):
            assert m._flatpak_filesystems("x") == set()

    def test_drift_fails_with_diff(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=(self.PERMS, 0, "")):
            try:
                m.flatpak_grants_exact_filesystems(None, "x", "xdg-run/gvfsd;host-os:ro;~/.var/app")
            except AssertionError as e:
                assert "unexpected: ['host']" in str(e)
            else:
                raise AssertionError("drift not detected")

    def test_not_installed_fails(self):
        m = _import_steps()
        with patch.object(m, "_run_host", return_value=("", 1, "not installed")):
            try:
                m.flatpak_grants_no_filesystems(None, "x")
            except AssertionError as e:
                assert "not installed" in str(e)
            else:
                raise AssertionError("missing app not detected")
