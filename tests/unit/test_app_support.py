"""Unit tests for tests/shared/app_support.py.

Tests _desktop_path, _flatpak_available, launch_target_available,
launch_background and atspi_click using mocks — no real filesystem or
subprocesses required.

Most classes force _IN_CONTAINER=False to exercise the local-filesystem code
paths; TestContainerMode forces it True to cover the SSH paths that behave
uses inside the runner container.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.shared import app_support

# Force non-container mode for all tests in this module.
_no_container = patch.object(app_support, "_IN_CONTAINER", False)


# ---------------------------------------------------------------------------
# _desktop_path
# ---------------------------------------------------------------------------

class TestDesktopPath:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_returns_path_when_desktop_file_exists(self, tmp_path):
        desktop_id = "org.gnome.Calculator.desktop"
        fake_dir = tmp_path / "applications"
        fake_dir.mkdir()
        (fake_dir / desktop_id).write_text("")

        with patch.object(app_support, "DESKTOP_DIRS", (str(fake_dir),)):
            result = app_support._desktop_path(desktop_id)

        assert result == str(fake_dir / desktop_id)

    def test_returns_none_when_no_desktop_file_found(self, tmp_path):
        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            result = app_support._desktop_path("io.missing.App.desktop")

        assert result is None

    def test_returns_first_matching_directory(self, tmp_path):
        desktop_id = "org.gnome.Calculator.desktop"
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / desktop_id).write_text("")
        (dir2 / desktop_id).write_text("")

        with patch.object(app_support, "DESKTOP_DIRS", (str(dir1), str(dir2))):
            result = app_support._desktop_path(desktop_id)

        assert result == str(dir1 / desktop_id)

    def test_skips_missing_directories_gracefully(self, tmp_path):
        desktop_id = "org.gnome.Calculator.desktop"
        missing_dir = str(tmp_path / "nonexistent")
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / desktop_id).write_text("")

        with patch.object(app_support, "DESKTOP_DIRS", (missing_dir, str(real_dir))):
            result = app_support._desktop_path(desktop_id)

        assert result == str(real_dir / desktop_id)


# ---------------------------------------------------------------------------
# _flatpak_available
# ---------------------------------------------------------------------------

class TestFlatpakAvailable:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_returns_true_when_flatpak_info_succeeds(self):
        fake_result = SimpleNamespace(returncode=0)
        with patch("tests.shared.app_support.subprocess.run",
                   return_value=fake_result) as mock_run:
            result = app_support._flatpak_available("org.gnome.Calculator")

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "flatpak"
        assert "org.gnome.Calculator" in cmd

    def test_returns_false_when_flatpak_info_fails(self):
        fake_result = SimpleNamespace(returncode=1)
        with patch("tests.shared.app_support.subprocess.run",
                   return_value=fake_result):
            result = app_support._flatpak_available("io.missing.App")

        assert result is False


# ---------------------------------------------------------------------------
# launch_target_available
# ---------------------------------------------------------------------------

class TestLaunchTargetAvailable:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_returns_true_for_available_command(self):
        targets = (("command", "bash"),)
        with patch.object(app_support.shutil, "which", return_value="/usr/bin/bash"):
            assert app_support.launch_target_available(targets) is True

    def test_returns_false_for_missing_command(self):
        targets = (("command", "nonexistent-tool-xyz"),)
        with patch.object(app_support.shutil, "which", return_value=None):
            assert app_support.launch_target_available(targets) is False

    def test_returns_true_for_available_desktop(self, tmp_path):
        desktop_id = "org.gnome.Calculator.desktop"
        (tmp_path / desktop_id).write_text("")
        targets = (("desktop", desktop_id),)
        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            assert app_support.launch_target_available(targets) is True

    def test_returns_false_for_missing_desktop(self, tmp_path):
        targets = (("desktop", "io.missing.App.desktop"),)
        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            assert app_support.launch_target_available(targets) is False

    def test_returns_true_for_available_flatpak(self):
        targets = (("flatpak", "org.gnome.Calculator"),)
        fake_result = SimpleNamespace(returncode=0)
        with patch("tests.shared.app_support.subprocess.run",
                   return_value=fake_result):
            assert app_support.launch_target_available(targets) is True

    def test_returns_false_when_no_candidates_match(self):
        targets = (
            ("command", "missing-cmd"),
            ("flatpak", "io.missing.App"),
        )
        with patch.object(app_support.shutil, "which", return_value=None):
            with patch("tests.shared.app_support.subprocess.run",
                       return_value=SimpleNamespace(returncode=1)):
                assert app_support.launch_target_available(targets) is False

    def test_returns_true_on_first_match_in_multi_target(self):
        targets = (
            ("command", "missing-cmd"),
            ("command", "bash"),
        )

        def fake_which(name):
            return "/usr/bin/bash" if name == "bash" else None

        with patch.object(app_support.shutil, "which", side_effect=fake_which):
            assert app_support.launch_target_available(targets) is True


# ---------------------------------------------------------------------------
# launch_background
# ---------------------------------------------------------------------------

class TestLaunchBackground:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_launches_command_when_available(self):
        targets = (("command", "bash"),)
        with patch.object(app_support.shutil, "which", return_value="/usr/bin/bash"):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                result = app_support.launch_background(targets)

        assert result == "command:bash"
        mock_popen.assert_called_once()

    def test_launches_desktop_file_when_available(self, tmp_path):
        desktop_id = "org.gnome.Calculator.desktop"
        (tmp_path / desktop_id).write_text("")
        targets = (("desktop", desktop_id),)
        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                result = app_support.launch_background(targets)

        assert result == f"desktop:{desktop_id}"
        mock_popen.assert_called_once()

    def test_launches_flatpak_when_available(self):
        targets = (("flatpak", "org.gnome.Calculator"),)
        with patch("tests.shared.app_support.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                result = app_support.launch_background(targets)

        assert result == "flatpak:org.gnome.Calculator"
        mock_popen.assert_called_once()

    def test_raises_when_no_candidate_available(self):
        targets = (("command", "missing-tool"),)
        with patch.object(app_support.shutil, "which", return_value=None):
            with pytest.raises(AssertionError, match="No launch candidate"):
                app_support.launch_background(targets)


# ---------------------------------------------------------------------------
# Launch environment forwarding
# ---------------------------------------------------------------------------

class TestLaunchEnvironment:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_env_exports_is_empty_without_env(self):
        assert app_support._env_exports(None) == ""
        assert app_support._env_exports({}) == ""

    def test_env_exports_quotes_values(self):
        rendered = app_support._env_exports({"A": "1", "B": "two words"})
        assert rendered == "export A=1; export B='two words'; "

    def test_flatpak_env_args_forwards_each_variable(self):
        assert app_support._flatpak_env_args({"GNOME_ACCESSIBILITY": "1"}) == [
            "--env=GNOME_ACCESSIBILITY=1"
        ]

    def test_flatpak_env_args_empty_without_env(self):
        assert app_support._flatpak_env_args(None) == []

    def test_command_launch_merges_env_into_os_environ(self):
        targets = (("command", "bash"),)
        with patch.object(app_support.shutil, "which", return_value="/usr/bin/bash"):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                app_support.launch_background(targets, env={"GNOME_ACCESSIBILITY": "1"})

        passed = mock_popen.call_args.kwargs["env"]
        assert passed["GNOME_ACCESSIBILITY"] == "1"
        assert "PATH" in passed

    def test_command_launch_without_env_inherits_environ(self):
        targets = (("command", "bash"),)
        with patch.object(app_support.shutil, "which", return_value="/usr/bin/bash"):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                app_support.launch_background(targets)

        assert mock_popen.call_args.kwargs["env"] is None

    def test_flatpak_launch_forwards_env_into_sandbox(self):
        targets = (("flatpak", "org.mozilla.firefox"),)
        with patch("tests.shared.app_support.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                app_support.launch_background(targets, env={"GNOME_ACCESSIBILITY": "1"})

        assert mock_popen.call_args.args[0] == [
            "flatpak", "run", "--env=GNOME_ACCESSIBILITY=1", "org.mozilla.firefox",
        ]

    def test_ssh_launch_exports_env_before_command(self):
        with patch("tests.shared.app_support.subprocess.run") as mock_run:
            app_support._ssh_launch("firefox", {"GNOME_ACCESSIBILITY": "1"})

        remote_cmd = mock_run.call_args.args[0][-1]
        assert "export GNOME_ACCESSIBILITY=1; nohup firefox" in remote_cmd


class TestFlatpakExportedDesktopEntries:
    def setup_method(self):
        _no_container.start()

    def teardown_method(self):
        _no_container.stop()

    def test_detects_system_flatpak_export(self):
        assert app_support._flatpak_desktop_app_id(
            "/var/lib/flatpak/exports/share/applications/org.mozilla.firefox.desktop",
            "org.mozilla.firefox.desktop",
        ) == "org.mozilla.firefox"

    def test_detects_user_flatpak_export(self):
        assert app_support._flatpak_desktop_app_id(
            "/home/u/.local/share/flatpak/exports/share/applications/org.mozilla.firefox.desktop",
            "org.mozilla.firefox.desktop",
        ) == "org.mozilla.firefox"

    def test_system_desktop_entry_is_not_a_flatpak_export(self):
        assert app_support._flatpak_desktop_app_id(
            "/usr/share/applications/firefox.desktop", "firefox.desktop"
        ) is None

    def test_flatpak_exported_desktop_forwards_env_into_sandbox(self, tmp_path):
        desktop_id = "org.mozilla.firefox.desktop"
        export_dir = tmp_path / "flatpak" / "exports" / "share" / "applications"
        export_dir.mkdir(parents=True)
        (export_dir / desktop_id).write_text("")

        with patch.object(app_support, "DESKTOP_DIRS", (str(export_dir),)):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                result = app_support.launch_background(
                    (("desktop", desktop_id),), env={"GNOME_ACCESSIBILITY": "1"}
                )

        assert result == "flatpak:org.mozilla.firefox"
        assert mock_popen.call_args.args[0] == [
            "flatpak", "run", "--env=GNOME_ACCESSIBILITY=1", "org.mozilla.firefox"
        ]

    def test_non_flatpak_desktop_still_uses_gtk_launch(self, tmp_path):
        desktop_id = "firefox.desktop"
        (tmp_path / desktop_id).write_text("")

        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            with patch("tests.shared.app_support.subprocess.Popen") as mock_popen:
                result = app_support.launch_background(
                    (("desktop", desktop_id),), env={"GNOME_ACCESSIBILITY": "1"}
                )

        assert result == f"desktop:{desktop_id}"
        assert mock_popen.call_args.args[0] == ["gtk-launch", desktop_id]
        assert mock_popen.call_args.kwargs["env"]["GNOME_ACCESSIBILITY"] == "1"

    def test_ssh_mode_flatpak_export_uses_flatpak_run(self):
        with patch.object(app_support, "_IN_CONTAINER", True):
            with patch.object(
                app_support,
                "_desktop_path",
                return_value="/var/lib/flatpak/exports/share/applications/org.mozilla.firefox.desktop",
            ):
                with patch("tests.shared.app_support.subprocess.run") as mock_run:
                    result = app_support.launch_background(
                        (("desktop", "org.mozilla.firefox.desktop"),),
                        env={"GNOME_ACCESSIBILITY": "1"},
                    )

        assert result == "flatpak:org.mozilla.firefox"
        remote_cmd = mock_run.call_args.args[0][-1]
        assert "flatpak run --env=GNOME_ACCESSIBILITY=1 org.mozilla.firefox" in remote_cmd
        assert "gio launch" not in remote_cmd


# ---------------------------------------------------------------------------
# SSH (runner-container) lookups and launches
# ---------------------------------------------------------------------------

def _ssh_result(returncode: int = 0, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


class TestContainerMode:
    """behave runs in the runner container, so these are the e2e code paths."""

    def setup_method(self):
        self._container = patch.object(app_support, "_IN_CONTAINER", True)
        self._container.start()

    def teardown_method(self):
        self._container.stop()

    def test_desktop_path_probes_vm_dirs_in_order(self):
        dirs = ("/a", "/b")
        replies = [_ssh_result(1), _ssh_result(0, "/b/x.desktop\n")]
        with patch.object(app_support, "DESKTOP_DIRS", dirs):
            with patch.object(app_support, "_ssh_run", side_effect=replies) as run:
                assert app_support._desktop_path("x.desktop") == "/b/x.desktop"

        assert [c.args[0] for c in run.call_args_list] == [
            "test -f /a/x.desktop && echo /a/x.desktop",
            "test -f /b/x.desktop && echo /b/x.desktop",
        ]

    def test_desktop_path_ignores_success_with_empty_stdout(self):
        with patch.object(app_support, "DESKTOP_DIRS", ("/a",)):
            with patch.object(app_support, "_ssh_run", return_value=_ssh_result(0, "  \n")):
                assert app_support._desktop_path("x.desktop") is None

    def test_desktop_path_does_not_touch_local_filesystem(self, tmp_path):
        (tmp_path / "x.desktop").write_text("")
        with patch.object(app_support, "DESKTOP_DIRS", (str(tmp_path),)):
            with patch.object(app_support, "_ssh_run", return_value=_ssh_result(1)):
                assert app_support._desktop_path("x.desktop") is None

    def test_flatpak_available_asks_the_vm(self):
        with patch.object(app_support, "_ssh_run", return_value=_ssh_result(0)) as run:
            assert app_support._flatpak_available("org.gnome.Calculator") is True
        run.assert_called_once_with("flatpak info org.gnome.Calculator 2>/dev/null")

    def test_flatpak_unavailable_on_vm(self):
        with patch.object(app_support, "_ssh_run", return_value=_ssh_result(1)):
            assert app_support._flatpak_available("org.gnome.Calculator") is False

    def test_command_target_available_checks_vm_not_runner(self):
        with patch.object(app_support.shutil, "which", return_value=None):
            with patch.object(app_support, "_ssh_run", return_value=_ssh_result(0)) as run:
                assert app_support.launch_target_available((("command", "gnome-calculator"),))
        run.assert_called_once_with("command -v gnome-calculator")

    def test_command_target_missing_on_vm_falls_through(self):
        with patch.object(app_support.shutil, "which", return_value="/usr/bin/gnome-calculator"):
            with patch.object(app_support, "_ssh_run", return_value=_ssh_result(1)):
                assert not app_support.launch_target_available((("command", "gnome-calculator"),))

    def test_launch_command_over_ssh(self):
        with patch.object(app_support, "_ssh_run", return_value=_ssh_result(0)):
            with patch.object(app_support, "_ssh_launch") as launch:
                with patch("tests.shared.app_support.subprocess.Popen") as popen:
                    result = app_support.launch_background(
                        (("command", "gnome-calculator"),), env={"A": "1"}
                    )

        assert result == "command:gnome-calculator"
        launch.assert_called_once_with("gnome-calculator", {"A": "1"})
        popen.assert_not_called()

    def test_launch_skips_command_missing_on_vm(self):
        with patch.object(app_support, "_ssh_run", return_value=_ssh_result(1)):
            with patch.object(app_support, "_ssh_launch") as launch:
                with pytest.raises(AssertionError, match="No launch candidate"):
                    app_support.launch_background((("command", "gnome-calculator"),))
        launch.assert_not_called()

    def test_launch_non_flatpak_desktop_uses_gio_launch(self):
        dp = "/usr/share/applications/org.gnome.Calculator.desktop"
        with patch.object(app_support, "_desktop_path", return_value=dp):
            with patch.object(app_support, "_ssh_launch") as launch:
                with patch("tests.shared.app_support.subprocess.Popen") as popen:
                    result = app_support.launch_background(
                        (("desktop", "org.gnome.Calculator.desktop"),)
                    )

        assert result == "desktop:org.gnome.Calculator.desktop"
        launch.assert_called_once_with(f"gio launch {dp}", None)
        popen.assert_not_called()


# ---------------------------------------------------------------------------
# atspi_click
# ---------------------------------------------------------------------------

class _FakeNode:
    def __init__(self, actions=None, failing=(), actions_error=None):
        self._actions = actions if actions is not None else {}
        self._failing = set(failing)
        self._actions_error = actions_error
        self.performed: list[str] = []
        self.clicked = False

    @property
    def actions(self):
        if self._actions_error:
            raise self._actions_error
        return self._actions

    def do_action_named(self, name):
        self.performed.append(name)
        if name in self._failing:
            raise RuntimeError(f"{name} failed")

    def click(self):
        self.clicked = True


class TestAtspiClick:
    @pytest.mark.parametrize("in_container", [True, False])
    def test_prefers_click_action(self, in_container):
        node = _FakeNode({"activate": None, "press": None, "click": None})
        with patch.object(app_support, "_IN_CONTAINER", in_container):
            app_support.atspi_click(node)
        assert node.performed == ["click"]
        assert not node.clicked

    def test_press_used_when_no_click_action(self):
        node = _FakeNode({"activate": None, "press": None})
        with patch.object(app_support, "_IN_CONTAINER", True):
            app_support.atspi_click(node)
        assert node.performed == ["press"]

    def test_falls_through_when_action_raises(self):
        node = _FakeNode({"click": None, "press": None, "activate": None},
                         failing={"click", "press"})
        with patch.object(app_support, "_IN_CONTAINER", True):
            app_support.atspi_click(node)
        assert node.performed == ["click", "press", "activate"]

    def test_container_raises_with_available_actions_when_none_usable(self):
        node = _FakeNode({"expand or contract": None})
        with patch.object(app_support, "_IN_CONTAINER", True):
            with pytest.raises(RuntimeError, match=r"available=\['expand or contract'\]"):
                app_support.atspi_click(node)
        assert not node.clicked

    def test_container_raises_when_every_action_fails(self):
        node = _FakeNode({"click": None}, failing={"click"})
        with patch.object(app_support, "_IN_CONTAINER", True):
            with pytest.raises(RuntimeError, match="no usable AT-SPI action"):
                app_support.atspi_click(node)

    def test_unreadable_actions_treated_as_none(self):
        node = _FakeNode(actions_error=RuntimeError("defunct"))
        with patch.object(app_support, "_IN_CONTAINER", True):
            with pytest.raises(RuntimeError, match=r"available=\[\]"):
                app_support.atspi_click(node)

    def test_none_actions_treated_as_none(self):
        node = _FakeNode()
        node._actions = None
        with patch.object(app_support, "_IN_CONTAINER", True):
            with pytest.raises(RuntimeError, match=r"available=\[\]"):
                app_support.atspi_click(node)

    def test_local_run_falls_back_to_coordinate_click(self):
        node = _FakeNode({"click": None}, failing={"click"})
        with patch.object(app_support, "_IN_CONTAINER", False):
            app_support.atspi_click(node)
        assert node.performed == ["click"]
        assert node.clicked
