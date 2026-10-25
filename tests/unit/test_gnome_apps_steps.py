"""Unit tests for gnome_apps_steps.py pure helper functions."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_gnome_apps(tree_available: bool = True, in_container: bool = False):
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

    app_support_stub = types.ModuleType("app_support")
    app_support_stub.launch_background = MagicMock()
    app_support_stub.launch_target_available = MagicMock(return_value=True)
    sys.modules["app_support"] = app_support_stub

    for key in list(sys.modules):
        if "gnome_apps_steps" in key:
            del sys.modules[key]

    with patch("os.path.lexists", return_value=in_container), \
         patch("os.path.isfile", return_value=not in_container):
        import tests.smoke.features.steps.gnome_apps_steps as m  # noqa: PLC0415
    return m


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestGnomeAppsConstants:
    def test_frame_roles_is_set(self):
        m = _import_gnome_apps()
        assert isinstance(m.FRAME_ROLES, set)
        assert "frame" in m.FRAME_ROLES
        assert "filler" in m.FRAME_ROLES

    def test_ptyxis_app_names_is_tuple(self):
        m = _import_gnome_apps()
        assert isinstance(m.PTYXIS_APP_NAMES, tuple)
        assert "ptyxis" in m.PTYXIS_APP_NAMES

    def test_files_app_names_is_tuple(self):
        m = _import_gnome_apps()
        assert isinstance(m.FILES_APP_NAMES, tuple)
        assert "nautilus" in m.FILES_APP_NAMES

    def test_app_wm_class_hints_has_ptyxis(self):
        m = _import_gnome_apps()
        assert "ptyxis" in m._APP_WM_CLASS_HINTS
        assert m._APP_WM_CLASS_HINTS["ptyxis"] == "ptyxis"

    def test_app_wm_class_hints_has_nautilus(self):
        m = _import_gnome_apps()
        assert "nautilus" in m._APP_WM_CLASS_HINTS


# ---------------------------------------------------------------------------
# _in_container
# ---------------------------------------------------------------------------

class TestInContainer:
    def test_false_outside(self):
        m = _import_gnome_apps(in_container=False)
        assert m._IN_CONTAINER is False

    def test_true_inside(self):
        m = _import_gnome_apps(in_container=True)
        assert m._IN_CONTAINER is True


# ---------------------------------------------------------------------------
# _skip_if_no_atspi
# ---------------------------------------------------------------------------

class TestSkipIfNoAtspi:
    def test_returns_false_when_tree_available(self):
        m = _import_gnome_apps(tree_available=True)
        context = MagicMock()
        assert m._skip_if_no_atspi(context) is False

    def test_returns_true_when_tree_none(self):
        m = _import_gnome_apps(tree_available=False)
        m.tree = None
        context = MagicMock()
        assert m._skip_if_no_atspi(context) is True

    def test_calls_scenario_skip_when_tree_none(self):
        m = _import_gnome_apps(tree_available=False)
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        context.scenario.skip.assert_called_once()

    def test_skip_message_mentions_at_spi(self):
        m = _import_gnome_apps(tree_available=False)
        m.tree = None
        context = MagicMock()
        m._skip_if_no_atspi(context)
        msg = context.scenario.skip.call_args[0][0]
        assert "AT-SPI" in msg


# ---------------------------------------------------------------------------
# _ssh_args
# ---------------------------------------------------------------------------

class TestSshArgs:
    def test_returns_list_starting_with_ssh(self):
        m = _import_gnome_apps()
        args = m._ssh_args()
        assert isinstance(args, list)
        assert args[0] == "ssh"

    def test_uses_env_ssh_key(self):
        m = _import_gnome_apps()
        with patch.dict(os.environ, {"SSH_KEY": "/tmp/testkey"}):
            args = m._ssh_args()
        assert "/tmp/testkey" in args

    def test_uses_env_vm_user_and_ip(self):
        m = _import_gnome_apps()
        with patch.dict(os.environ, {"VM_USER": "testuser", "VM_IP": "10.0.0.1"}):
            args = m._ssh_args()
        assert "testuser@10.0.0.1" in args

    def test_uses_default_ip_when_not_set(self):
        m = _import_gnome_apps()
        env = {k: v for k, v in os.environ.items() if k not in ("VM_IP", "VM_USER")}
        with patch.dict(os.environ, env, clear=True):
            args = m._ssh_args()
        assert "bluefin-test@127.0.0.1" in args

    def test_includes_strict_host_key_checking_no(self):
        m = _import_gnome_apps()
        args = m._ssh_args()
        assert "StrictHostKeyChecking=no" in args

    def test_includes_port_argument(self):
        m = _import_gnome_apps()
        with patch.dict(os.environ, {"SSH_PORT": "2222"}):
            args = m._ssh_args()
        assert "-p" in args
        idx = args.index("-p")
        assert args[idx + 1] == "2222"


# ---------------------------------------------------------------------------
# _shell_eval_force_close — WM hint resolution
# ---------------------------------------------------------------------------

class TestShellEvalForceClose:
    def test_noop_when_no_matching_hint(self):
        m = _import_gnome_apps()
        with patch("subprocess.run") as mock_run:
            m._shell_eval_force_close(("com.example.unknown",))
        mock_run.assert_not_called()

    def test_calls_subprocess_for_known_app(self):
        m = _import_gnome_apps(in_container=False)
        m._IN_CONTAINER = False
        with patch("subprocess.run") as mock_run, patch("time.sleep"):
            mock_run.return_value = MagicMock(returncode=0)
            m._shell_eval_force_close(("ptyxis",))
        mock_run.assert_called_once()

    def test_includes_wm_class_hint_in_js(self):
        m = _import_gnome_apps(in_container=False)
        m._IN_CONTAINER = False
        captured_js = []
        def capture_run(cmd, **kwargs):
            if isinstance(cmd, list):
                captured_js.extend(cmd)
            return MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=capture_run), patch("time.sleep"):
            m._shell_eval_force_close(("ptyxis",))
        full_cmd = " ".join(str(a) for a in captured_js)
        assert "ptyxis" in full_cmd

    def test_routes_via_ssh_in_container(self):
        m = _import_gnome_apps(in_container=True)
        m._IN_CONTAINER = True
        captured = []
        def capture_run(cmd, **kwargs):
            captured.append(cmd)
            return MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=capture_run), patch("time.sleep"):
            m._shell_eval_force_close(("ptyxis",))
        assert any("ssh" in str(c) for c in captured)


class TestPtyxisLaunch:
    def test_ptyxis_accepts_shell_prompt_window_title(self):
        m = _import_gnome_apps()
        frame = MagicMock()
        frame.roleName = "frame"
        frame.showing = True
        frame.name = "bluefin-test@runner:~"
        app = MagicMock()
        app.findChildren = MagicMock(return_value=[frame])
        app.children = [frame]

        with patch.object(m, "_launch_app"), \
             patch.object(m, "_app", return_value=app), \
             patch.object(m, "_shell_eval_force_close"), \
             patch.object(m, "_wait_for_app_to_close"), \
             patch.object(m, "_wait_for_app_or_window_to_close"):
            context = MagicMock()
            m.ptyxis_terminal_launches_successfully(context)
            assert context.last_launched_app_window is frame


class TestWindowDeadline:
    @pytest.fixture
    def clock(self, monkeypatch):
        m = _import_gnome_apps()
        clock = types.SimpleNamespace(now=100.0)

        def advance(seconds):
            clock.now += seconds

        clock.advance = advance
        monkeypatch.setattr(m, "monotonic", lambda: clock.now)
        monkeypatch.setattr(m, "sleep", advance)
        # The old per-alias fallback would spend ten seconds on every miss.
        def retrying_application(name):
            advance(10)
            raise LookupError(name)

        m.tree.root.application.side_effect = retrying_application
        return m, clock

    @pytest.mark.parametrize("registered", [False, True])
    def test_files_missing_window_fails_within_elapsed_budget(self, clock, registered):
        m, clock = clock
        app = MagicMock(name="files-app")
        app.name = "org.gnome.Nautilus"
        app.findChildren.return_value = []

        def applications():
            clock.advance(0.1)  # Discovery itself consumes the budget, not just sleep.
            return [app] if registered else []

        m.tree.root.applications.side_effect = applications
        context = MagicMock()
        with patch.object(m, "_launch_app"), \
             pytest.raises(AssertionError, match="Visible Files window not found"):
            m.files_file_manager_launches_successfully(context)

        assert clock.now - 100.0 == pytest.approx(15, abs=0.2)
        m.tree.root.application.assert_not_called()
        context.execute_steps.assert_not_called()

    @pytest.mark.parametrize("fallback", [False, True])
    def test_late_app_and_matching_window_succeed(self, clock, fallback):
        m, clock = clock
        frame = types.SimpleNamespace(roleName="frame", showing=True, name=" Home ")
        app = MagicMock()
        app.name = ' "ORG.GNOME.NAUTILUS service" '
        app.findChildren.side_effect = lambda pred: [frame] if pred(frame) else []
        m.tree.root.applications.side_effect = lambda: [app] if clock.now >= 101 else []
        m.tree.root.findChildren.return_value = []
        wait = m._wait_for_window_or_title if fallback else m._wait_for_window

        assert wait(m.FILES_APP_NAMES, {"Files", "Home"}, "Files", timeout=1.5) is frame
        assert 1 <= clock.now - 100.0 < 1.5
        m.tree.root.application.assert_not_called()

    def test_title_fallback_succeeds_without_second_budget(self, clock):
        m, clock = clock
        frame = types.SimpleNamespace(roleName="filler", showing=True, name=" Clocks ")
        m.tree.root.applications.return_value = []
        m.tree.root.findChildren.side_effect = lambda pred: (
            [frame] if clock.now >= 100.6 and pred(frame) else []
        )

        assert m._wait_for_window_or_title(
            m.CLOCKS_APP_NAMES, {"Clocks"}, "Clocks", timeout=1
        ) is frame
        assert 0.6 <= clock.now - 100.0 < 1
        m.tree.root.application.assert_not_called()

    @pytest.mark.parametrize("fallback", [False, True])
    def test_hidden_wrong_role_and_wrong_title_still_fail(self, clock, fallback):
        m, clock = clock
        frames = [
            types.SimpleNamespace(roleName="frame", showing=False, name="Home"),
            types.SimpleNamespace(roleName="label", showing=True, name="Home"),
            types.SimpleNamespace(roleName="filler", showing=True, name="Other"),
        ]
        app = MagicMock()
        app.name = "Files"
        app.findChildren.side_effect = lambda pred: [f for f in frames if pred(f)]
        m.tree.root.applications.return_value = [app]
        m.tree.root.findChildren.side_effect = app.findChildren.side_effect
        wait = m._wait_for_window_or_title if fallback else m._wait_for_window

        with pytest.raises(AssertionError, match="Other"):
            wait(m.FILES_APP_NAMES, {"Home"}, "Files", timeout=0.7)
        assert clock.now - 100.0 == pytest.approx(0.7)
        m.tree.root.application.assert_not_called()

    def test_discovery_exhaustion_does_not_start_window_or_fallback_search(self, clock):
        m, clock = clock
        app = MagicMock()
        app.name = "Files"

        def applications():
            clock.advance(1)
            return [app]

        m.tree.root.applications.side_effect = applications
        with pytest.raises(AssertionError, match="Visible Files window not found"):
            m._wait_for_window_or_title(m.FILES_APP_NAMES, {"Home"}, "Files", timeout=1)
        assert clock.now - 100.0 == 1
        app.findChildren.assert_not_called()
        m.tree.root.findChildren.assert_not_called()

    def test_title_fallback_does_not_accept_unrelated_shell_prompt(self, clock):
        m, clock = clock
        frame = types.SimpleNamespace(roleName="frame", showing=True, name="other@runner:~")
        m.tree.root.applications.return_value = []
        m.tree.root.findChildren.side_effect = lambda pred: [frame] if pred(frame) else []

        with pytest.raises(AssertionError, match="by title"):
            m._wait_for_window_or_title(m.CLOCKS_APP_NAMES, {"Clocks"}, "Clocks", timeout=1)
        assert clock.now - 100.0 == pytest.approx(1)

    def test_registered_app_waits_for_late_visible_window(self, clock):
        m, clock = clock
        frame = types.SimpleNamespace(
            get_role_name=lambda: "frame", get_name=lambda: "Home", showing=True
        )
        app = MagicMock()
        app.name = "Files"
        app.findChildren.side_effect = lambda pred: (
            [frame] if clock.now >= 100.5 and pred(frame) else []
        )
        m.tree.root.applications.return_value = [app]

        assert m._wait_for_window(m.FILES_APP_NAMES, {"Home"}, "Files", timeout=0.75) is frame
        assert clock.now - 100.0 == 0.5

    @pytest.mark.parametrize("fallback", [False, True])
    def test_match_found_by_traversal_straddling_deadline_is_returned(self, clock, fallback):
        m, clock = clock
        frame = types.SimpleNamespace(roleName="frame", showing=True, name="Home")

        def slow_find(pred):
            clock.advance(0.3)
            return [frame] if pred(frame) else []

        app = MagicMock()
        app.name = "Files"
        if fallback:
            m.tree.root.applications.return_value = []
            m.tree.root.findChildren.side_effect = slow_find
        else:
            app.findChildren.side_effect = slow_find
            m.tree.root.applications.return_value = [app]
        wait = m._wait_for_window_or_title if fallback else m._wait_for_window

        assert wait(m.FILES_APP_NAMES, {"Home"}, "Files", timeout=0.25) is frame
