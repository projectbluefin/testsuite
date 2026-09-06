"""Unit tests for tests/shared/gnome_shell_steps.py.

Tests _eval_bool, _wait_eval_bool, and _shell_eval using subprocess mocks.
These functions parse Shell.Eval output and drive boolean assertions in
the smoke and vanilla-gnome suites.
"""

from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to avoid importing the full behave/dogtail stack
# ---------------------------------------------------------------------------

def _import_gnome_shell_steps():
    """Import the module under test, skipping behave decorator registration."""
    import sys

    # Stub out behave.step so @step decorators don't explode without a running
    # behave context.
    behave_stub = MagicMock()
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules.setdefault("behave", behave_stub)
    sys.modules.setdefault("behave.runner", MagicMock())

    # Force reimport from the real path
    if "tests.shared.gnome_shell_steps" in sys.modules:
        del sys.modules["tests.shared.gnome_shell_steps"]

    import tests.shared.gnome_shell_steps as m
    return m


# ---------------------------------------------------------------------------
# _shell_eval
# ---------------------------------------------------------------------------

class TestShellEval:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def _make_completed(self, stdout="", stderr="", returncode=0):
        proc = MagicMock()
        proc.stdout = stdout
        proc.stderr = stderr
        proc.returncode = returncode
        return proc

    def test_returns_stdout_on_success(self):
        proc = self._make_completed(stdout="(true, 'true')\n")
        with patch("subprocess.run", return_value=proc), \
             patch.object(self.mod, "_IN_CONTAINER", False):
            result = self.mod._shell_eval("Main.overview.visible")
        assert result == "(true, 'true')\n"

    def test_raises_on_nonzero_returncode(self):
        proc = self._make_completed(returncode=1, stderr="DBus error")
        with patch("subprocess.run", return_value=proc), \
             patch.object(self.mod, "_IN_CONTAINER", False):
            with pytest.raises(AssertionError, match="Shell.Eval failed"):
                self.mod._shell_eval("bad.js")

    def test_passes_js_to_subprocess(self):
        proc = self._make_completed(stdout="(true, 'true')\n")
        with patch("subprocess.run", return_value=proc) as mock_run, \
             patch.object(self.mod, "_IN_CONTAINER", False):
            self.mod._shell_eval("Main.overview.visible")
        call_args = mock_run.call_args[0][0]
        # JS is now prefixed with unsafe_mode; check it appears in the last arg.
        assert any("Main.overview.visible" in str(a) for a in call_args)

    def test_uses_gdbus_call(self):
        proc = self._make_completed(stdout="(true, 'true')\n")
        with patch("subprocess.run", return_value=proc) as mock_run, \
             patch.object(self.mod, "_IN_CONTAINER", False):
            self.mod._shell_eval("x")
        call_args = mock_run.call_args[0][0]
        assert "gdbus" in call_args[0]
        assert "org.gnome.Shell" in call_args

    def test_uses_ssh_in_container(self):
        """In container mode, gdbus is forwarded via SSH to the host VM."""
        proc = self._make_completed(stdout="(true, 'true')\n")
        with patch("subprocess.run", return_value=proc) as mock_run, \
             patch.object(self.mod, "_IN_CONTAINER", True):
            self.mod._shell_eval("Main.overview.visible")
        call_args = mock_run.call_args[0][0]
        # First arg is "ssh", rest is SSH options and the gdbus command string.
        assert call_args[0] == "ssh"
        cmd_str = call_args[-1]
        assert "gdbus" in cmd_str
        assert "org.gnome.Shell" in cmd_str
        assert "Main.overview.visible" in cmd_str


# ---------------------------------------------------------------------------
# _eval_bool
# ---------------------------------------------------------------------------

class TestEvalBool:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def _patch_shell_eval(self, stdout):
        return patch.object(self.mod, "_shell_eval", return_value=stdout)

    def test_true_quoted(self):
        with self._patch_shell_eval("(true, 'true')\n"):
            assert self.mod._eval_bool("x") is True

    def test_false_quoted(self):
        with self._patch_shell_eval("(true, 'false')\n"):
            assert self.mod._eval_bool("x") is False

    def test_case_insensitive_true(self):
        with self._patch_shell_eval("(true, 'True')\n"):
            assert self.mod._eval_bool("x") is True

    def test_raises_on_unparseable_output(self):
        with self._patch_shell_eval("unexpected garbage\n"):
            with pytest.raises(AssertionError, match="Could not parse boolean"):
                self.mod._eval_bool("x")

    def test_raises_on_empty_output(self):
        with self._patch_shell_eval(""):
            with pytest.raises(AssertionError, match="Could not parse boolean"):
                self.mod._eval_bool("x")


# ---------------------------------------------------------------------------
# _wait_eval_bool
# ---------------------------------------------------------------------------

class TestWaitEvalBool:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def test_returns_true_immediately_when_value_matches(self):
        with patch.object(self.mod, "_eval_bool", return_value=True):
            with patch("time.sleep"):
                assert self.mod._wait_eval_bool("x", True, retries=3) is True

    def test_retries_until_match(self):
        side_effects = [False, False, True]
        call_count = {"n": 0}

        def _mock_eval_bool(js):
            val = side_effects[call_count["n"]]
            call_count["n"] += 1
            return val

        with patch.object(self.mod, "_eval_bool", side_effect=_mock_eval_bool):
            with patch("time.sleep"):
                result = self.mod._wait_eval_bool("x", True, retries=5)
        assert result is True
        assert call_count["n"] == 3

    def test_returns_false_when_retries_exhausted(self):
        with patch.object(self.mod, "_eval_bool", return_value=False):
            with patch("time.sleep"):
                assert self.mod._wait_eval_bool("x", True, retries=3) is False

    def test_tolerates_assertion_errors_during_retries(self):
        side_effects = [AssertionError("parse error"), AssertionError("parse error"), True]

        def _mock_eval_bool(js):
            val = side_effects.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        with patch.object(self.mod, "_eval_bool", side_effect=_mock_eval_bool):
            with patch("time.sleep"):
                result = self.mod._wait_eval_bool("x", True, retries=5)
        assert result is True

    def test_matching_false_value(self):
        with patch.object(self.mod, "_eval_bool", return_value=False):
            with patch("time.sleep"):
                assert self.mod._wait_eval_bool("x", False, retries=3) is True


# ---------------------------------------------------------------------------
# Step function helpers
# ---------------------------------------------------------------------------


def _make_node(role="panel", name="", showing=True, children=None):
    node = MagicMock()
    node.roleName = role
    node.name = name
    node.showing = showing
    node.children = children or []
    node.findChildren = lambda fn: [c for c in node.children if fn(c)]
    return node


def _make_context(shell):
    context = MagicMock()
    context.sandbox = MagicMock()
    context.sandbox.shell = shell
    return context


# ---------------------------------------------------------------------------
# AT-SPI step functions
# ---------------------------------------------------------------------------


class TestAtspiSteps:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def test_dump_panel_children_prints_tree(self, capsys):
        toggle = _make_node(role="toggle button", name="7:14 PM")
        panel = _make_node(role="panel", name="top-bar", children=[toggle])
        shell = _make_node(role="application", name="gnome-shell", children=[panel])

        self.mod.dump_panel_children(_make_context(shell))

        out = capsys.readouterr().out
        assert "=== GNOME-SHELL AT-SPI TREE ===" in out
        assert "role='panel'" in out
        assert "name='7:14 PM'" in out
        assert "=== END AT-SPI TREE ===" in out

    def test_dump_panel_children_swallows_exceptions(self, capsys):
        context = MagicMock()
        sandbox = MagicMock()
        type(sandbox).shell = PropertyMock(side_effect=RuntimeError("boom"))
        context.sandbox = sandbox

        self.mod.dump_panel_children(context)

        out = capsys.readouterr().out
        assert "dump_panel_children failed: boom" in out

    def test_dump_atspi_tree_writes_expected_content(self):
        toggle = _make_node(role="toggle button", name="System")
        panel = _make_node(role="panel", name="top-bar", children=[toggle])
        shell = _make_node(role="application", name="gnome-shell", children=[panel])
        context = _make_context(shell)

        mocked_open = mock_open()
        with patch("os.makedirs") as mock_makedirs, \
             patch("builtins.open", mocked_open), \
             patch("tests.shared.gnome_shell_steps.resolve_results_dir", return_value="/tmp/results"):
            self.mod.dump_atspi_tree(context)

        mock_makedirs.assert_called_once_with("/tmp/results", exist_ok=True)
        mocked_open.assert_called_once_with("/tmp/results/atspi_tree.txt", "w")
        written = "".join(call.args[0] for call in mocked_open().write.call_args_list)
        assert "role='application'" in written
        assert "name='gnome-shell'" in written
        assert "role='panel'" in written
        assert "name='System'" in written

    def test_gnome_shell_is_accessible_succeeds_when_shell_exists(self):
        shell = _make_node(role="application", name="gnome-shell")
        context = MagicMock()
        sandbox = MagicMock()
        type(sandbox).shell = PropertyMock(return_value=shell)
        context.sandbox = sandbox

        with patch.object(self.mod, "sleep"):
            self.mod.gnome_shell_is_accessible(context)

    def test_gnome_shell_is_accessible_retries_then_raises(self):
        context = MagicMock()
        sandbox = MagicMock()
        type(sandbox).shell = PropertyMock(return_value=None)
        context.sandbox = sandbox

        with patch.object(self.mod, "sleep") as mock_sleep:
            with pytest.raises(AssertionError, match="gnome-shell not accessible via AT-SPI"):
                self.mod.gnome_shell_is_accessible(context)

        assert mock_sleep.call_count == 6

    def test_panel_is_present_sets_context_panel(self):
        panel = _make_node(role="panel", name="top-bar")
        shell = _make_node(role="application", name="gnome-shell", children=[panel])
        context = _make_context(shell)

        self.mod.panel_is_present(context)

        assert context.panel is panel

    def test_panel_is_present_raises_without_panel(self):
        child = _make_node(role="label", name="Activities")
        shell = _make_node(role="application", name="gnome-shell", children=[child])
        context = _make_context(shell)

        with pytest.raises(AssertionError, match=r"Panel \(role='panel'\) not found"):
            self.mod.panel_is_present(context)

    def test_clock_toggle_visible_finds_clock_by_time_name(self):
        clock = _make_node(role="toggle button", name="7:14 PM", showing=False)
        panel = _make_node(
            role="panel",
            children=[
                _make_node(role="toggle button", name="Activities", showing=False),
                clock,
                _make_node(role="toggle button", name="System", showing=False),
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        self.mod.clock_toggle_visible(context)

        assert context.clock_toggle is clock

    def test_clock_toggle_visible_excludes_non_clock_names(self):
        fallback = _make_node(role="toggle button", name="Bluetooth", showing=False)
        panel = _make_node(
            role="panel",
            children=[
                _make_node(role="toggle button", name="Activities", showing=False),
                _make_node(role="toggle button", name="System", showing=False),
                fallback,
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        self.mod.clock_toggle_visible(context)

        assert context.clock_toggle is fallback

    def test_system_menu_toggle_visible_finds_system_toggle(self):
        system = _make_node(role="toggle button", name="System", showing=False)
        panel = _make_node(
            role="panel",
            children=[
                _make_node(role="toggle button", name="Activities", showing=False),
                _make_node(role="toggle button", name="7:14 PM", showing=False),
                system,
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        self.mod.system_menu_toggle_visible(context)

        assert context.system_toggle is system

    def test_system_menu_toggle_visible_falls_back_to_nonstandard_name(self):
        fallback = _make_node(role="toggle button", name="Sound", showing=False)
        panel = _make_node(
            role="panel",
            children=[
                _make_node(role="toggle button", name="Activities", showing=False),
                _make_node(role="toggle button", name="7:14 PM", showing=False),
                fallback,
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        self.mod.system_menu_toggle_visible(context)

        assert context.system_toggle is fallback

    def test_activities_toggle_in_panel_finds_activities(self):
        activities = _make_node(role="toggle button", name="Activities", showing=False)
        panel = _make_node(
            role="panel",
            children=[
                activities,
                _make_node(role="toggle button", name="7:14 PM", showing=False),
                _make_node(role="toggle button", name="System", showing=False),
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        self.mod.activities_toggle_in_panel(context)

        assert context.activities_toggle is activities

    def test_activities_toggle_in_panel_raises_when_missing(self):
        panel = _make_node(
            role="panel",
            children=[
                _make_node(role="toggle button", name="7:14 PM", showing=False),
                _make_node(role="toggle button", name="System", showing=False),
            ],
        )
        shell = _make_node(role="application", children=[panel])
        context = _make_context(shell)

        with pytest.raises(AssertionError, match="Activities toggle button not found"):
            self.mod.activities_toggle_in_panel(context)


# ---------------------------------------------------------------------------
# String comparison step
# ---------------------------------------------------------------------------


class TestLastCommandOutputStrippedIs:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def test_matches_stripped_command_stdout(self):
        context = MagicMock(command_stdout=" expected\n")

        self.mod.last_command_output_stripped_is(context, "expected")

    def test_raises_on_mismatch(self):
        context = MagicMock(last_command_output="actual\n")

        with pytest.raises(AssertionError, match="Wanted output: 'expected'"):
            self.mod.last_command_output_stripped_is(context, "expected")


# ---------------------------------------------------------------------------
# Shell.Eval step functions
# ---------------------------------------------------------------------------


class TestShellEvalSteps:
    def setup_method(self):
        self.mod = _import_gnome_shell_steps()

    def test_close_overview_eval_calls_shell_eval(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(self.mod, "sleep"):
            self.mod.close_overview_eval(MagicMock())

        mock_shell_eval.assert_called_once_with("Main.overview.hide()")

    def test_open_quick_settings_eval_returns_when_open_first_try(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(
            self.mod, "_eval_bool", return_value=True
        ) as mock_eval_bool, patch.object(self.mod, "sleep"):
            self.mod.open_quick_settings_eval(MagicMock())

        assert [call.args[0] for call in mock_shell_eval.call_args_list] == [
            "global.context.unsafe_mode = true",
            "if (!Main.panel.statusArea.quickSettings.menu.isOpen)"
            " Main.panel.statusArea.quickSettings.menu.open(0)",
        ]
        mock_eval_bool.assert_called_once_with("Main.panel.statusArea.quickSettings.menu.isOpen.toString()")

    def test_open_quick_settings_eval_retries_until_open(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(
            self.mod, "_eval_bool", side_effect=[False, False, True]
        ) as mock_eval_bool, patch.object(self.mod, "sleep"):
            self.mod.open_quick_settings_eval(MagicMock())

        assert mock_shell_eval.call_count == 4
        assert mock_eval_bool.call_count == 3

    def test_quick_settings_closed_eval_passes_when_wait_succeeds(self):
        with patch.object(self.mod, "_wait_eval_bool", return_value=True) as mock_wait_eval_bool:
            self.mod.quick_settings_closed_eval(MagicMock())

        mock_wait_eval_bool.assert_called_once_with(
            "Main.panel.statusArea.quickSettings.menu.isOpen.toString()",
            expected=False,
            retries=8,
            delay=0.5,
        )

    def test_quick_settings_closed_eval_raises_when_still_open(self):
        with patch.object(self.mod, "_wait_eval_bool", return_value=False), patch.object(
            self.mod, "_shell_eval", return_value="(true, 'true')"
        ):
            with pytest.raises(AssertionError, match="Quick Settings still open"):
                self.mod.quick_settings_closed_eval(MagicMock())

    def test_open_date_menu_eval_returns_when_open_first_try(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(
            self.mod, "_eval_bool", return_value=True
        ) as mock_eval_bool, patch.object(self.mod, "sleep"):
            self.mod.open_date_menu_eval(MagicMock())

        assert [call.args[0] for call in mock_shell_eval.call_args_list] == [
            "global.context.unsafe_mode = true",
            "if (!Main.panel.statusArea.dateMenu.menu.isOpen)"
            " Main.panel.statusArea.dateMenu.menu.open(0)",
        ]
        mock_eval_bool.assert_called_once_with("Main.panel.statusArea.dateMenu.menu.isOpen.toString()")

    def test_open_date_menu_eval_retries_until_open(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(
            self.mod, "_eval_bool", side_effect=[False, False, True]
        ) as mock_eval_bool, patch.object(self.mod, "sleep"):
            self.mod.open_date_menu_eval(MagicMock())

        assert mock_shell_eval.call_count == 4
        assert mock_eval_bool.call_count == 3

    def test_close_quick_settings_eval_calls_shell_eval(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(self.mod, "sleep"):
            self.mod.close_quick_settings_eval(MagicMock())

        mock_shell_eval.assert_called_once_with("Main.panel.statusArea.quickSettings.menu.close(0)")

    def test_close_date_menu_eval_calls_shell_eval(self):
        with patch.object(self.mod, "_shell_eval") as mock_shell_eval, patch.object(self.mod, "sleep"):
            self.mod.close_date_menu_eval(MagicMock())

        mock_shell_eval.assert_called_once_with("Main.panel.statusArea.dateMenu.menu.close(0)")

    def test_date_menu_closed_eval_passes_when_wait_succeeds(self):
        with patch.object(self.mod, "_wait_eval_bool", return_value=True) as mock_wait_eval_bool:
            self.mod.date_menu_closed_eval(MagicMock())

        mock_wait_eval_bool.assert_called_once_with(
            "Main.panel.statusArea.dateMenu.menu.isOpen.toString()",
            expected=False,
            retries=8,
            delay=0.5,
        )

    def test_date_menu_closed_eval_raises_when_still_open(self):
        with patch.object(self.mod, "_wait_eval_bool", return_value=False), patch.object(
            self.mod, "_shell_eval", return_value="(true, 'true')"
        ):
            with pytest.raises(AssertionError, match="Date menu still open"):
                self.mod.date_menu_closed_eval(MagicMock())
