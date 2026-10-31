"""Unit tests for tests/software/features/steps/steps.py helpers."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_software_steps(in_container: bool = False):
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    ssh_steps_stub = types.ModuleType("tests.shared.ssh_steps")
    sys.modules["tests.shared"] = sys.modules.get("tests.shared", types.ModuleType("tests.shared"))
    sys.modules["tests.shared.ssh_steps"] = ssh_steps_stub


    for key in list(sys.modules):
        if "software.features.steps.steps" in key:
            del sys.modules[key]

    with patch("os.path.lexists", return_value=in_container), \
         patch("os.path.isfile", return_value=not in_container):
        import tests.software.features.steps.steps as m  # noqa: PLC0415
    return m


def _completed(stdout="", rc=0, stderr=""):
    r = MagicMock()
    r.stdout = stdout
    r.returncode = rc
    r.stderr = stderr
    return r


# ---------------------------------------------------------------------------
# _IN_CONTAINER
# ---------------------------------------------------------------------------

class TestInContainer:
    def test_false_outside_container(self):
        m = _import_software_steps(in_container=False)
        assert m._IN_CONTAINER is False

    def test_true_inside_container(self):
        m = _import_software_steps(in_container=True)
        assert m._IN_CONTAINER is True


# ---------------------------------------------------------------------------
# _flatpak — routing
# ---------------------------------------------------------------------------

class TestFlatpakRouting:
    def test_uses_ssh_when_in_container(self):
        m = _import_software_steps(in_container=True)
        m._IN_CONTAINER = True
        ctx = MagicMock()
        ctx.config.userdata = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["list"])
        call_args = mock_run.call_args[0][0]
        assert "ssh" in call_args[0]

    def test_uses_flatpak_directly_when_not_in_container(self):
        m = _import_software_steps(in_container=False)
        m._IN_CONTAINER = False
        ctx = MagicMock()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["list"])
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "flatpak"

    def test_passes_flatpak_args_in_non_container(self):
        m = _import_software_steps(in_container=False)
        m._IN_CONTAINER = False
        ctx = MagicMock()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["permissions", "mytable"])
        call_args = mock_run.call_args[0][0]
        assert "flatpak" in call_args
        assert "permissions" in call_args
        assert "mytable" in call_args

    def test_ssh_contains_flatpak_command(self):
        m = _import_software_steps(in_container=True)
        m._IN_CONTAINER = True
        ctx = MagicMock()
        ctx.config.userdata = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["override", "--user", "myapp"])
        call_args = mock_run.call_args[0][0]
        # Last element is the shell command string sent via SSH
        ssh_cmd = call_args[-1]
        assert "flatpak" in ssh_cmd
        assert "override" in ssh_cmd

    def test_uses_env_ssh_key_in_container(self):
        m = _import_software_steps(in_container=True)
        m._IN_CONTAINER = True
        ctx = MagicMock()
        ctx.config.userdata = {}
        # MagicMock attribute reads return truthy mocks, so clear the
        # context attributes to force resolution from the environment.
        ctx.ssh_key = ""
        ctx.vm_ip = ""
        ctx.ssh_user = ""
        ctx.ssh_port = ""
        with patch("subprocess.run") as mock_run, \
             patch.dict(os.environ, {"SSH_KEY": "/tmp/mykey"}):
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["list"])
        call_args = mock_run.call_args[0][0]
        assert "/tmp/mykey" in call_args

    def test_uses_context_ssh_attributes_when_set(self):
        """Connection details must come from the same context attributes
        the shared run_ssh() steps use — one source, not two (#712)."""
        m = _import_software_steps(in_container=True)
        m._IN_CONTAINER = True
        ctx = MagicMock()
        ctx.config.userdata = {}
        ctx.ssh_key = "/tmp/context-key"
        ctx.vm_ip = "10.0.0.9"
        ctx.ssh_user = "ctxuser"
        ctx.ssh_port = "2222"
        with patch("subprocess.run") as mock_run, \
             patch.dict(os.environ, {"SSH_KEY": "/tmp/env-key", "VM_IP": "192.0.2.1"}):
            mock_run.return_value = _completed()
            m._flatpak(ctx, ["list"])
        call_args = mock_run.call_args[0][0]
        assert "/tmp/context-key" in call_args
        assert "2222" in call_args
        assert "ctxuser@10.0.0.9" in call_args


class TestFlatpakContextForwarding:
    @pytest.mark.parametrize(
        ("step_name", "args", "stdout"),
        [
            ("set_flatpak_user_override", ("--filesystem=home", "myapp"), ""),
            ("reset_flatpak_user_overrides", ("myapp",), ""),
            ("no_flatpak_user_overrides_exist", ("myapp",), "[Context]\n"),
            ("flatpak_remote_is_configured", ("flathub",), "flathub\n"),
            ("flatpak_app_is_installed", ("myapp",), "myapp\n"),
            ("flatpak_app_is_not_installed", ("myapp",), ""),
        ],
    )
    def test_step_forwards_context_to_flatpak(self, step_name, args, stdout):
        m = _import_software_steps()
        ctx = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed(stdout=stdout)) as flatpak:
            getattr(m, step_name)(ctx, *args)
        assert flatpak.call_args.args[0] is ctx

    def test_bazaar_process_probe_forwards_context(self):
        m = _import_software_steps()
        ctx = MagicMock()
        output = "Application\nio.github.kolunmi.Bazaar\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output)) as flatpak:
            assert m._bazaar_flatpak_is_running(ctx)
        assert flatpak.call_args.args[0] is ctx

    def test_bazaar_close_wait_forwards_context(self):
        m = _import_software_steps()
        ctx = MagicMock()
        with patch.object(m, "_visible_bazaar_window", side_effect=LookupError), \
             patch.object(m, "_bazaar_flatpak_is_running", return_value=False) as running:
            m._wait_for_bazaar_to_close(ctx)
        running.assert_called_once_with(ctx)


# ---------------------------------------------------------------------------
# Bazaar AT-SPI lookup — bounded, Bazaar-only, content-proving
# ---------------------------------------------------------------------------

def _node(name="", role="", showing=True, children=(), descendants=(), **attrs):
    node = types.SimpleNamespace(name=name, roleName=role, showing=showing, children=list(children), **attrs)
    node.findChildren = lambda pred: [n for n in descendants if pred(n)]
    return node


def _with_apps(m, *apps):
    m.tree = types.SimpleNamespace(root=types.SimpleNamespace(applications=lambda: list(apps)))


class TestBazaarLookup:
    def test_finds_bazaar_by_gtk4_prgname(self):
        m = _import_software_steps()
        window = _node("Bazaar", "frame")
        _with_apps(m, _node("gnome-shell"), _node("bazaar", children=[window]))
        assert m._visible_bazaar_window() is window

    def test_gnome_software_is_not_bazaar(self):
        m = _import_software_steps()
        _with_apps(m, _node("gnome-software", children=[_node("Bazaar", "frame")]))
        with pytest.raises(LookupError, match="gnome-software"):
            m._bazaar_app()

    def test_window_wait_honours_deadline(self):
        m = _import_software_steps()
        _with_apps(m)
        with patch.object(m, "POLL_INTERVAL", 0.01), pytest.raises(AssertionError, match="Visible Bazaar window"):
            m._bazaar_window(timeout=0.05)

    def test_poll_retries_probe_errors(self):
        m = _import_software_steps()
        outcomes = iter([RuntimeError("cache drop"), None, "ok"])

        def probe():
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(m, "POLL_INTERVAL", 0):
            assert m._poll("x", 5, probe) == "ok"

    def test_refreshing_window_shows_no_view(self):
        """Header chrome is showing while every view page is still hidden."""
        m = _import_software_steps()
        hidden = _node("Explore", "panel", descendants=[_node("tile", "label", showing=False)])
        window = _node("Bazaar", "frame", descendants=[_node("Explore", "page tab"), hidden])
        with pytest.raises(LookupError, match="Refreshing"):
            m._shown_bazaar_view(window)

    def test_view_requires_named_panel_content_and_selected_tab(self):
        m = _import_software_steps()
        panel = _node("Library", "panel", descendants=[_node("Calculator", "label")])
        tab = _node("Library", "page tab", selected=True)
        window = _node("Bazaar", "frame", descendants=[tab, panel])
        _with_apps(m, _node("bazaar", children=[window]))
        assert m._bazaar_view("Library") is panel
        with pytest.raises(LookupError, match="not 'Search'"):
            m._bazaar_view("Search")
        tab.selected = False
        with pytest.raises(LookupError, match="not selected"):
            m._bazaar_view("Library")

    def test_process_probe_fails_closed(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(rc=1, stderr="boom")):
            with pytest.raises(AssertionError, match="flatpak ps failed"):
                m._bazaar_flatpak_is_running(MagicMock())

    def test_missing_window_reports_the_launch_state(self):
        """Run 41224716141: the launch never reached AT-SPI; say how far it got."""
        m = _import_software_steps()
        m.tree = object()
        state = _completed(stdout="● app-flatpak-io.github.kolunmi.Bazaar-42.scope\n  └─9 flatpak run")
        with patch.object(m, "_bazaar_window", side_effect=AssertionError("Visible Bazaar window not reached")), \
             patch.object(m, "_run_in_session", return_value=state) as run:
            with pytest.raises(AssertionError, match="(?s)not reached.*Bazaar launch state.*flatpak run"):
                m.bazaar_main_window_is_accessible(MagicMock())
        assert "app-flatpak-io.github.kolunmi.Bazaar-*.scope" in run.call_args.args[1]

    def test_launch_state_probe_never_hides_the_window_failure(self):
        m = _import_software_steps()
        m.tree = object()
        with patch.object(m, "_bazaar_window", side_effect=AssertionError("Visible Bazaar window not reached")), \
             patch.object(m, "_run_in_session", side_effect=TimeoutError("ssh")):
            with pytest.raises(AssertionError, match="(?s)not reached.*launch state unavailable: TimeoutError"):
                m.bazaar_main_window_is_accessible(MagicMock())

    def test_launch_state_probes_processes_bus_names_and_a11y_bus(self):
        """Run 41227112796: /app/bin/bazaar sat at 210 ms CPU with no window or portal call."""
        import subprocess
        m = _import_software_steps()
        script = m._BAZAAR_LAUNCH_STATE
        assert subprocess.run(["bash", "-n", "-c", script], capture_output=True).returncode == 0
        for probe in ("wchan:32", "cgroup.procs", "GetNameOwner", "io.github.kolunmi.Bazaar.SearchProvider",
                      "org.a11y.Bus.GetAddress", "--timeout 3"):
            assert probe in script, probe
        with patch.object(m, "_run_in_session", return_value=_completed(stdout="state")) as run:
            assert m._bazaar_launch_state(MagicMock()) == "state"
        assert run.call_args.kwargs["timeout"] == 30


class TestBazaarSearchLocators:
    """Run 41201865894: the field showed "flatseal" and the Flatseal tile was
    visible, but the step looked for a `text` node (GtkText has role NONE)."""

    @staticmethod
    def _search_view(m, *content):
        panel = _node("Search", "panel", descendants=list(content))
        tab = _node("Search", "page tab", selected=True)
        window = _node("Bazaar", "frame", descendants=[tab, panel])
        _with_apps(m, _node("bazaar", children=[window]))

    @staticmethod
    def _expired_clock(m):
        clock = patch.object(m, "time")
        mocked = clock.start()
        mocked.monotonic.side_effect = [0, 100]
        return clock

    def test_field_is_the_search_box_entry(self):
        m = _import_software_steps()
        self._search_view(m, _node("", "entry", text="flatseal"), _node("Flatseal", "label"))
        m.bazaar_search_field_shows(MagicMock(), "flatseal")

    def test_a_text_node_is_not_the_search_field(self):
        m = _import_software_steps()
        self._search_view(m, _node("", "text", text="flatseal"))
        clock = self._expired_clock(m)
        try:
            with patch.object(m, "POLL_INTERVAL", 0), pytest.raises(AssertionError, match="entry"):
                m.bazaar_search_field_shows(MagicMock(), "flatseal")
        finally:
            clock.stop()

    def test_field_reports_what_it_holds(self):
        m = _import_software_steps()
        self._search_view(m, _node("", "entry", text="flat"))
        clock = self._expired_clock(m)
        try:
            with patch.object(m, "POLL_INTERVAL", 0), pytest.raises(AssertionError, match="found \\['flat'\\]"):
                m.bazaar_search_field_shows(MagicMock(), "flatseal")
        finally:
            clock.stop()

    def test_result_is_a_visible_label_with_the_app_title(self):
        m = _import_software_steps()
        self._search_view(m, _node("", "entry", text="flatseal"), _node("Flatseal", "label"))
        m.bazaar_search_results_include(MagicMock(), "Flatseal")
        self._search_view(m, _node("", "entry", text="flatseal"), _node("Flatseal", "label", showing=False))
        clock = self._expired_clock(m)
        try:
            with patch.object(m, "POLL_INTERVAL", 0), pytest.raises(AssertionError, match="Flatseal"):
                m.bazaar_search_results_include(MagicMock(), "Flatseal")
        finally:
            clock.stop()


class TestBazaarTransaction:
    """Bazaar 0.9.10: search result → app page → Install → Remove, on the VM's system installation."""

    APP = "com.belmoussaoui.Decoder"

    @staticmethod
    def _keyboard(key, combo):
        utility = types.ModuleType("qecore.utility")
        utility.keyboard_key_input = key
        utility.keyboard_key_combo_input = combo
        return patch.dict(sys.modules, {"qecore.utility": utility})

    def test_keyboard_opens_the_first_result_through_its_grid_cell(self):
        m = _import_software_steps()
        get = _node("Get", "push button", focused=False)
        panel = _node("Search", "panel", descendants=[get])
        window = _node("Bazaar", "frame", descendants=[_node("Search", "page tab", selected=True), panel])
        page = _node("Bazaar — Decoder", "frame", showing=False)
        _with_apps(m, _node("bazaar", children=[window, page]))
        keys = []

        def key(name):
            keys.append(name)
            if len(keys) == 1:
                get.focused = True  # search_activate focuses the first tile's Get button
            else:
                window.showing, page.showing = False, True

        def combo(name):
            keys.append(name)
            get.focused = False

        with self._keyboard(key, combo), patch.object(m, "bazaar_window_has_keyboard_focus") as focus, \
                patch.object(m, "POLL_INTERVAL", 0):
            m.open_bazaar_search_result(MagicMock(), "Decoder")
        focus.assert_called_once()
        assert keys == ["ENTER", "<LEFTSHIFT><TAB>", "ENTER"]

    def test_page_lookup_names_the_window_title(self):
        m = _import_software_steps()
        _with_apps(m, _node("bazaar", children=[_node("Bazaar — Decoder Plus", "frame")]))
        with pytest.raises(LookupError, match="'Bazaar — Decoder'.*Decoder Plus"):
            m._bazaar_page("Decoder")

    def test_install_clicks_install_then_waits_for_the_system_ref_and_open(self):
        m = _import_software_steps()
        install = _node("Install", "push button")
        open_button = _node("Open", "push button", showing=False)
        hidden_narrow = _node("Install", "push button", showing=False)
        page = _node("Bazaar — Decoder", "frame", descendants=[hidden_narrow, install, open_button])
        _with_apps(m, _node("bazaar", children=[page]))
        info = iter([_completed(rc=1), _completed(rc=0)])

        def click(node):
            assert node is install
            install.showing, open_button.showing = False, True

        with patch.object(m, "atspi_click", side_effect=click), \
                patch.object(m, "_flatpak", side_effect=lambda *a, **kw: next(info)) as flatpak, \
                patch.object(m, "POLL_INTERVAL", 0):
            m.install_from_bazaar_page(MagicMock(), self.APP, "Decoder")
        assert flatpak.call_args.args[1] == ["info", "--system", self.APP]

    @pytest.mark.parametrize("name", ["Uninstall Application", "Remove"])
    def test_remove_uses_either_layout_button_and_waits_for_absence(self, name):
        m = _import_software_steps()
        remove = _node(name, "push button")
        install = _node("Install", "push button", showing=False)
        _with_apps(m, _node("bazaar", children=[_node("Bazaar — Decoder", "frame", descendants=[remove, install])]))
        info = iter([_completed(rc=0), _completed(rc=1)])

        def click(node):
            assert node is remove
            remove.showing, install.showing = False, True

        with patch.object(m, "atspi_click", side_effect=click), \
                patch.object(m, "_flatpak", side_effect=lambda *a, **kw: next(info)), \
                patch.object(m, "POLL_INTERVAL", 0):
            m.remove_from_bazaar_page(MagicMock(), self.APP, "Decoder")

    def test_a_failed_flatpak_probe_is_not_an_answer(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(rc=255, stderr="ssh: connect")):
            with pytest.raises(AssertionError, match="rc=255"):
                m._system_flatpak_installed(MagicMock(), self.APP)

    def test_polkit_check_covers_every_transaction_action(self):
        import subprocess
        m = _import_software_steps()
        script = m._BAZAAR_POLKIT_CHECK
        assert subprocess.run(["bash", "-n", "-c", script], capture_output=True).returncode == 0
        assert "app-install runtime-install app-uninstall runtime-uninstall" in script
        assert "--allow-user-interaction" not in script
        denied = _completed(stdout="== org.freedesktop.Flatpak.app-install\npolkit\\56result=auth_admin_keep\n", rc=4)
        with patch.object(m, "_run_in_session", return_value=denied):
            with pytest.raises(AssertionError, match="(?s)without a prompt.*auth_admin_keep"):
                m.bazaar_needs_no_polkit_prompt(MagicMock())

    def test_preinstalled_app_or_user_data_fails_the_precondition(self):
        m = _import_software_steps()
        ctx = MagicMock()
        with patch.object(m, "_run_in_session", return_value=_completed(stdout="has-user-data")):
            with pytest.raises(AssertionError, match="has-user-data"):
                m.flatpak_app_absent_with_cleanup(ctx, self.APP)
        ctx.add_cleanup.assert_not_called()
        with patch.object(m, "_run_in_session", return_value=_completed()):
            m.flatpak_app_absent_with_cleanup(ctx, self.APP)
        ctx.add_cleanup.assert_called_once_with(m._uninstall_flatpak_app, ctx, self.APP)

    def test_cleanup_uninstalls_each_scope_and_reports_failure(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed()) as run:
            m._uninstall_flatpak_app(MagicMock(), self.APP)
        cmd = run.call_args.args[1]
        assert f"sudo -n flatpak uninstall -y --noninteractive --system {self.APP} || exit 1" in cmd
        assert f"flatpak uninstall -y --noninteractive --user {self.APP} || exit 1" in cmd
        with patch.object(m, "_run_in_session", return_value=_completed(rc=1, stderr="busy")):
            with pytest.raises(AssertionError, match="busy"):
                m._uninstall_flatpak_app(MagicMock(), self.APP)


class TestBazaarYamlCheck:
    """Run the shipped YAML check script against real files."""

    @staticmethod
    def _run(m, directory):
        import subprocess
        return subprocess.run(
            [sys.executable, "-c", m._BAZAAR_YAML_CHECK, str(directory)],
            capture_output=True, text=True,
        )

    def test_valid_mappings_pass(self, tmp_path):
        m = _import_software_steps()
        (tmp_path / "bazaar.yaml").write_text("curated-config-paths:\n  - /x.yaml\n")
        result = self._run(m, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "bazaar.yaml" in result.stdout

    @pytest.mark.parametrize("files", [
        {}, {"a.yaml": ""}, {"a.yaml": "- list\n"}, {"a.yaml": "a: [\n"}, {"a.yaml": "{}\n"},
        {"a.yaml": "a: 1\n---\nb: 2\n"}, {"a.yaml": "a: 1\n", "b.yaml": "scalar\n"},
    ])
    def test_empty_doc_non_mapping_syntax_error_and_multi_document_fail(self, tmp_path, files):
        m = _import_software_steps()
        for name, text in files.items():
            (tmp_path / name).write_text(text)
        assert self._run(m, tmp_path).returncode != 0

    def test_step_reports_failure(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed(rc=1, stderr="no *.yaml files")):
            with pytest.raises(AssertionError, match="no \\*.yaml files"):
                m.bazaar_yaml_files_parse(MagicMock(), "/etc/bazaar")

    def test_step_quotes_script_for_the_remote_shell(self):
        """Regression: Gherkin kept the old step's backslash quotes, so python3 hit SyntaxError."""
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed()) as run:
            m.bazaar_yaml_files_parse(MagicMock(), "/etc/bazaar")
        import shlex
        argv = shlex.split(run.call_args.args[1])
        assert argv == ["python3", "-c", m._BAZAAR_YAML_CHECK, "/etc/bazaar"]


class TestUinputUsage:
    """qecore 4.19.3 builds KEY_<TOKEN> per combo token, and python-uinput's
    _chars_to_events maps only unshifted characters (others become None)."""

    def test_close_shortcut_uses_evdev_modifier_names(self):
        m = _import_software_steps()
        ctx = MagicMock()
        with patch.object(m, "focus_the_bazaar_window") as focus, \
             patch.object(m, "_wait_for_bazaar_to_close"):
            m.tree = object()
            m.close_bazaar_via_shortcut(ctx)
        focus.assert_called_once_with(ctx)
        ctx.execute_steps.assert_called_once_with('* Key combo: "<LEFTCTRL><Q>" with uinput')

    def test_keys_wait_for_an_active_bazaar_window(self):
        m = _import_software_steps()
        window = _node("Bazaar", "frame", active=False)
        _with_apps(m, _node("bazaar", children=[window]))
        with patch.object(m, "POLL_INTERVAL", 0.01), patch.object(m, "time") as clock:
            clock.monotonic.side_effect = [0, 0, 10]
            with pytest.raises(AssertionError, match="not the active window"):
                m.bazaar_window_has_keyboard_focus(MagicMock())
        window.active = True
        with patch.object(m, "_uinput_keyboard_ready") as ready:
            m.bazaar_window_has_keyboard_focus(MagicMock())
        ready.assert_called_once_with()

    def test_uinput_keyboard_is_created_then_awaited_in_the_shell_seat(self):
        """Run 41216246249: the first key of a fresh device was lost ("latseal")."""
        m = _import_software_steps()
        utility = types.ModuleType("qecore.utility")
        calls = []
        utility._get_uinput_device = MagicMock(side_effect=lambda: calls.append("device"))
        seat = iter([False, True])

        def listed(js):
            calls.append("seat")
            return next(seat)

        with patch.dict(sys.modules, {"qecore.utility": utility}), \
             patch.object(m, "_shell_eval_bool", side_effect=listed) as shell, \
             patch.object(m, "POLL_INTERVAL", 0):
            m._uinput_keyboard_ready()
        assert calls == ["device", "seat", "seat"]
        js = shell.call_args.args[0]
        assert "get_default_seat().list_devices()" in js and "'python-uinput'" in js

    def test_uinput_keyboard_missing_from_seat_fails(self):
        m = _import_software_steps()
        utility = types.ModuleType("qecore.utility")
        utility._get_uinput_device = MagicMock()
        with patch.dict(sys.modules, {"qecore.utility": utility}), \
             patch.object(m, "_shell_eval_bool", return_value=False), \
             patch.object(m, "POLL_INTERVAL", 0.01):
            with pytest.raises(AssertionError, match="python-uinput keyboard in the GNOME Shell seat"):
                m._uinput_keyboard_ready(timeout=0.05)

    def test_focus_activates_bazaar_through_shell_then_requires_active(self):
        """Run 41210513366: an SSH-launched window was mapped without focus."""
        m = _import_software_steps()
        window = _node("Bazaar", "frame", active=True)
        _with_apps(m, _node("bazaar", children=[window]))
        with patch.object(m, "_shell_eval_bool", return_value=True) as shell, \
             patch.object(m, "_uinput_keyboard_ready"):
            m.focus_the_bazaar_window(MagicMock())
        js = shell.call_args.args[0]
        assert "Main.activateWindow(win)" in js
        assert "'io.github.kolunmi.Bazaar'" in js and "get_title() === 'Bazaar'" in js

    def test_focus_fails_when_shell_has_no_bazaar_window(self):
        m = _import_software_steps()
        _with_apps(m, _node("bazaar", children=[_node("Bazaar", "frame", active=True)]))
        with patch.object(m, "_shell_eval_bool", return_value=False):
            with pytest.raises(AssertionError, match="no Bazaar MetaWindow"):
                m.focus_the_bazaar_window(MagicMock())

    def test_focus_still_requires_atspi_active_after_activation(self):
        m = _import_software_steps()
        _with_apps(m, _node("bazaar", children=[_node("Bazaar", "frame", active=False)]))
        with patch.object(m, "_shell_eval_bool", return_value=True), \
             patch.object(m, "_bazaar_window"), \
             patch.object(m, "POLL_INTERVAL", 0), patch.object(m, "time") as clock:
            clock.monotonic.side_effect = [0, 10]
            with pytest.raises(AssertionError, match="not the active window"):
                m.focus_the_bazaar_window(MagicMock())

    def test_typed_uinput_text_is_unshifted(self):
        import re
        from pathlib import Path
        features = Path(__file__).resolve().parents[1] / "software" / "features"
        typed = [
            text for f in features.glob("*.feature")
            for text in re.findall(r'Type text: "([^"]*)" with uinput', f.read_text())
        ]
        assert typed
        for text in typed:
            assert re.fullmatch(r"[a-z0-9 ]+", text), text


class TestWelcomeModal:
    """Bluefin's first-run Shell modal grabs the keyboard (run 41196660163); its St
    buttons have no AT-SPI actions (run 41199678665), so Escape (Skip's key) closes it."""

    def _shell(self, m, skip):
        _with_apps(m, _node("gnome-shell", descendants=[skip] if skip else []))

    @staticmethod
    def _keyboard(side_effect=None):
        utility = types.ModuleType("qecore.utility")
        utility.keyboard_key_input = MagicMock(side_effect=side_effect)
        return patch.dict(sys.modules, {"qecore.utility": utility}), utility.keyboard_key_input

    def test_absent_modal_is_a_no_op(self):
        m = _import_software_steps()
        self._shell(m, None)
        modules, key = self._keyboard()
        with modules:
            m.dismiss_bluefin_welcome_dialog()
        key.assert_not_called()

    def test_escape_is_pressed_once_the_keyboard_is_registered(self):
        m = _import_software_steps()
        skip = _node("Skip", "push button")
        self._shell(m, skip)
        order = []

        def escape(name):
            order.append(name)
            skip.showing = False

        modules, key = self._keyboard(side_effect=escape)
        with modules, patch.object(m, "atspi_click") as click, \
             patch.object(m, "_uinput_keyboard_ready", side_effect=lambda: order.append("ready")):
            m.dismiss_bluefin_welcome_dialog()
        key.assert_called_once_with("ESC")
        assert order == ["ready", "ESC"]
        click.assert_not_called()

    def test_modal_that_stays_fails(self):
        m = _import_software_steps()
        self._shell(m, _node("Skip", "push button"))
        modules, _ = self._keyboard()
        with modules, patch.object(m, "POLL_INTERVAL", 0.01), patch.object(m, "_uinput_keyboard_ready"):
            with pytest.raises(AssertionError, match="welcome dialog dismissed"):
                m.dismiss_bluefin_welcome_dialog(timeout=0.05)

    def test_only_gnome_shell_buttons_count(self):
        m = _import_software_steps()
        _with_apps(m, _node("bazaar", descendants=[_node("Skip", "push button")]))
        assert m._welcome_skip_buttons() == []


class TestVmCoredumpStep:
    def test_no_entries_passes(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed(rc=1)):
            m.no_vm_coredump_entries_exist(MagicMock(), "bazaar")

    @pytest.mark.parametrize(("rc", "match"), [(0, "Unexpected coredump"), (127, "coredumpctl failed")])
    def test_entries_or_errors_fail(self, rc, match):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed(rc=rc, stdout="bazaar 1234")):
            with pytest.raises(AssertionError, match=match):
                m.no_vm_coredump_entries_exist(MagicMock(), "bazaar")


# ---------------------------------------------------------------------------
# environment.py — fail-closed Bazaar probe, GUI-only sandbox hooks
# ---------------------------------------------------------------------------

def _import_software_environment():
    for name in ("qecore", "qecore.sandbox", "qecore.common_steps"):
        stub = types.ModuleType(name)
        stub.TestSandbox = MagicMock
        sys.modules[name] = stub
    sys.modules.pop("tests.software.features.environment", None)
    import tests.software.features.environment as env  # noqa: PLC0415
    return env


def _scenario(*tags, status="passed"):
    return types.SimpleNamespace(
        tags=set(tags), effective_tags=set(tags), feature=types.SimpleNamespace(tags=set()),
        name="s", skip=MagicMock(), status=types.SimpleNamespace(name=status),
    )


class TestSoftwareEnvironment:
    @pytest.mark.parametrize(("rc", "present"), [(0, True), (1, False)])
    def test_probe_reads_presence(self, rc, present):
        env = _import_software_environment()
        with patch("subprocess.run", return_value=_completed(rc=rc)):
            assert env._has_bazaar(MagicMock()) is present

    @pytest.mark.parametrize("rc", [2, 255])
    def test_probe_fails_closed_on_ssh_or_flatpak_error(self, rc):
        env = _import_software_environment()
        with patch("subprocess.run", return_value=_completed(rc=rc, stderr="Connection refused")):
            with pytest.raises(RuntimeError, match="Connection refused"):
                env._has_bazaar(MagicMock())

    def test_cli_scenario_skips_gui_hooks(self):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(sandbox=MagicMock(_scenario_skipped=True))
        scenario = _scenario("software", "flatpak_cli")
        with patch.object(env, "_stop_bazaar") as stop, \
             patch.object(env, "_dismiss_bluefin_welcome_dialog") as modal, \
             patch.object(env, "take_screenshot"), patch.object(env, "record_end"):
            env.before_scenario(ctx, scenario)
            env.after_scenario(ctx, scenario)
        ctx.sandbox.before_scenario.assert_not_called()
        ctx.sandbox.after_scenario.assert_not_called()
        stop.assert_not_called()
        modal.assert_not_called()
        assert ctx.sandbox._scenario_skipped is False, "qecore after_all would assert"

    def test_skipped_scenario_leaves_qecore_no_scenario_check_armed(self):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(sandbox=MagicMock(_scenario_skipped=True))
        with patch.object(env, "_has_bazaar", return_value=False):
            env.before_scenario(ctx, _scenario("software", "bazaar_ui"))
        assert ctx.sandbox._scenario_skipped is True

    def test_gui_scenario_runs_hooks_and_stops_bazaar(self):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(sandbox=MagicMock())
        scenario = _scenario("software", "bazaar_ui")
        with patch.object(env, "_has_bazaar", return_value=True), \
             patch.object(env, "_stop_bazaar") as stop, \
             patch.object(env, "_dismiss_bluefin_welcome_dialog") as modal, \
             patch.object(env, "take_screenshot"), patch.object(env, "record_end"):
            env.before_scenario(ctx, scenario)
            env.after_scenario(ctx, scenario)
        ctx.sandbox.before_scenario.assert_called_once_with(ctx, scenario)
        ctx.sandbox.after_scenario.assert_called_once_with(ctx, scenario)
        stop.assert_called_once_with(ctx)
        modal.assert_called_once_with()

    def test_stop_kills_bazaar_scopes_and_waits_until_none_are_active(self, tmp_path):
        """Run the real teardown script against a fake systemctl whose scope dies on SIGKILL."""
        import subprocess
        env = _import_software_environment()
        calls = tmp_path / "calls"
        fake = tmp_path / "systemctl"
        fake.write_text(
            "#!/bin/bash\n"
            f'echo "$*" >> {calls}\n'
            f'if [[ "$*" == *"list-units"* ]] && ! grep -q -- "--signal=SIGKILL" {calls}; then\n'
            '  echo "app-flatpak-io.github.kolunmi.Bazaar-1.scope loaded active running"\n'
            "fi\n"
        )
        fake.chmod(0o755)
        result = subprocess.run(
            ["bash", "-c", env.STOP_BAZAAR], capture_output=True, text=True, timeout=20,
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        )
        assert result.returncode == 0, result.stderr
        first, second = calls.read_text().splitlines()[:2]
        assert first == "--user kill --signal=SIGKILL app-flatpak-io.github.kolunmi.Bazaar-*.scope"
        assert second.startswith("--user list-units --state=active")

    @pytest.mark.parametrize("outcome", [_completed(rc=1, stdout="still running"), TimeoutError("ssh")])
    def test_stop_reports_but_never_raises(self, outcome, capsys):
        env = _import_software_environment()
        side_effect = outcome if isinstance(outcome, Exception) else None
        with patch("subprocess.run", return_value=outcome, side_effect=side_effect):
            env._stop_bazaar(MagicMock())
        assert "WARNING" in capsys.readouterr().out

    @pytest.mark.parametrize(("image", "bluefin"), [
        ("ghcr.io/projectbluefin/bluefin@sha256:460d3a74", True),
        ("ghcr.io/projectbluefin/bluefin-dx:testing", True),
        ("ghcr.io/projectbluefin/dakota:testing", False),
        ("ghcr.io/projectbluefin/utah:latest", False),
        ("", False),
    ])
    def test_bluefin_is_matched_on_image_name_not_org(self, image, bluefin):
        assert _import_software_environment()._is_bluefin_image(image) is bluefin

    @pytest.mark.parametrize(("image", "skipped"), [
        ("ghcr.io/projectbluefin/bluefin@sha256:460d3a74", True),
        ("ghcr.io/projectbluefin/dakota:testing", False),
    ])
    def test_skip_bluefin_gate(self, image, skipped):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(sandbox=MagicMock(), config=types.SimpleNamespace(userdata={}))
        scenario = _scenario("software", "flatpak_cli", "flatpark", "skip_bluefin")
        with patch.dict(os.environ, {"IMAGE": image}):
            env.before_scenario(ctx, scenario)
        if skipped:
            scenario.skip.assert_called_once_with(reason=env.SKIP_BLUEFIN_REASON)
            assert "#1549" in env.SKIP_BLUEFIN_REASON
        else:
            scenario.skip.assert_not_called()

    def test_skip_bluefin_reads_userdata_when_image_env_unset(self):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(config=types.SimpleNamespace(
            userdata={"image": "ghcr.io/projectbluefin/bluefin:stable"}))
        scenario = _scenario("software", "flatpak_cli", "skip_bluefin")
        with patch.dict(os.environ, {"IMAGE": ""}):
            env.before_scenario(ctx, scenario)
        scenario.skip.assert_called_once_with(reason=env.SKIP_BLUEFIN_REASON)

    def test_skip_bluefin_prefers_base_image_over_composed_image(self):
        env = _import_software_environment()
        ctx = types.SimpleNamespace(config=types.SimpleNamespace(userdata={}))
        scenario = _scenario("software", "flatpak_cli", "skip_bluefin")
        with patch.dict(os.environ, {
            "BASE_IMAGE": "ghcr.io/projectbluefin/bluefin:stable",
            "IMAGE": "ghcr.io/projectbluefin/testsuite-e2e:run-1",
        }):
            env.before_scenario(ctx, scenario)
        scenario.skip.assert_called_once_with(reason=env.SKIP_BLUEFIN_REASON)

    def test_only_flatpark_scenarios_carry_skip_bluefin(self):
        from pathlib import Path
        import re
        feature = Path(__file__).resolve().parents[1] / "software" / "features" / "compass_flatpark.feature"
        lines = feature.read_text().splitlines()
        for i, line in enumerate(lines):
            if re.match(r"\s*Scenario:", line):
                tags = set(re.findall(r"@(\w+)", lines[i - 1]))
                assert ("skip_bluefin" in tags) == ("flatpark" in tags), line
        other = (Path(__file__).resolve().parents[1] / "software" / "features").glob("*.feature")
        assert [f.name for f in other if "@skip_bluefin" in f.read_text()] == ["compass_flatpark.feature"]


# ---------------------------------------------------------------------------
# flatpak_permissions_table_is_queryable — assertion logic
# ---------------------------------------------------------------------------

class TestFlatpakPermissionsTable:
    def test_passes_on_rc_zero(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(rc=0)):
            ctx = MagicMock()
            m.flatpak_permissions_table_is_queryable(ctx, "notifications")

    def test_passes_on_no_permissions_in_stdout(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="No permissions", rc=1)):
            ctx = MagicMock()
            m.flatpak_permissions_table_is_queryable(ctx, "notifications")

    def test_passes_on_no_permissions_in_stderr(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stderr="No permissions", rc=1)):
            ctx = MagicMock()
            m.flatpak_permissions_table_is_queryable(ctx, "notifications")

    def test_raises_on_unexpected_failure(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="fatal error", rc=1)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="failed unexpectedly"):
                m.flatpak_permissions_table_is_queryable(ctx, "notifications")


# ---------------------------------------------------------------------------
# no_flatpak_user_overrides_exist — keyfile key detection
# ---------------------------------------------------------------------------

class TestNoFlatpakUserOverridesExist:
    def test_passes_on_empty_output(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=0)):
            m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_raises_when_keyfile_entry_remains(self):
        m = _import_software_steps()
        import pytest
        output = "[Context]\nfilesystems=home;\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="found active override keys"):
                m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_bare_section_header_is_not_an_override(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="[Context]\n", rc=0)):
            m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_raises_on_nonzero_rc(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=1)):
            with pytest.raises(AssertionError, match="failed"):
                m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")


# ---------------------------------------------------------------------------
# flatpak_app_info_is_queryable — new step
# ---------------------------------------------------------------------------

class TestFlatpakAppInfoIsQueryable:
    def test_passes_when_app_id_in_output(self):
        m = _import_software_steps()
        app_id = "io.github.kolunmi.Bazaar"
        output = f"Application ID: {app_id}\nBranch: stable\nOrigin: flathub\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            ctx = MagicMock()
            m.flatpak_app_info_is_queryable(ctx, app_id)

    def test_raises_when_rc_nonzero(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=1)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="failed"):
                m.flatpak_app_info_is_queryable(ctx, "io.github.kolunmi.Bazaar")

    def test_raises_when_app_id_missing_from_output(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="some other app", rc=0)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="not found"):
                m.flatpak_app_info_is_queryable(ctx, "io.github.kolunmi.Bazaar")


# ---------------------------------------------------------------------------
# flatpak_app_is_from_remote — new step
# ---------------------------------------------------------------------------

class TestFlatpakAppIsFromRemote:
    def test_passes_when_remote_in_output(self):
        m = _import_software_steps()
        output = "Application ID: io.github.kolunmi.Bazaar\nOrigin: flathub\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            ctx = MagicMock()
            m.flatpak_app_is_from_remote(ctx, "io.github.kolunmi.Bazaar", "flathub")

    def test_another_remote_containing_the_name_is_rejected(self):
        m = _import_software_steps()
        output = "          ID: io.github.kolunmi.Bazaar\n      Origin: flathub-beta\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="origin \\['flathub-beta'\\]"):
                m.flatpak_app_is_from_remote(MagicMock(), "io.github.kolunmi.Bazaar", "flathub")

    def test_raises_when_remote_missing(self):
        m = _import_software_steps()
        output = "Application ID: io.github.kolunmi.Bazaar\nOrigin: sideload\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="not 'flathub'"):
                m.flatpak_app_is_from_remote(MagicMock(), "io.github.kolunmi.Bazaar", "flathub")

    def test_raises_when_rc_nonzero(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=1)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="failed"):
                m.flatpak_app_is_from_remote(ctx, "io.github.kolunmi.Bazaar", "flathub")


# ---------------------------------------------------------------------------
# no_flatpak_user_overrides_exist — [Environment] overrides
# ---------------------------------------------------------------------------

class TestNoFlatpakUserOverridesExistEnvironment:
    """`flatpak override --env=` is recorded under [Environment].

    An allow-list of [Context] keys alone reported "no overrides exist" while
    environment overrides were still live on the app.
    """

    def test_environment_override_is_detected(self):
        m = _import_software_steps()
        output = "[Environment]\nBLUEFIN_TESTSUITE=1\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="Environment.BLUEFIN_TESTSUITE"):
                m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_environment_override_after_context_section_is_detected(self):
        m = _import_software_steps()
        output = "[Context]\n\n[Environment]\nFOO=a=b\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="Environment.FOO"):
                m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_bare_environment_header_is_not_an_override(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="[Environment]\n", rc=0)):
            m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")

    def test_unknown_context_key_is_ignored(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="[Context]\nunknown=x;\n", rc=0)):
            m.no_flatpak_user_overrides_exist(MagicMock(), "myapp")


# ---------------------------------------------------------------------------
# flatpak_permissions_table_is_queryable — output content, not just rc
# ---------------------------------------------------------------------------

class TestFlatpakPermissionsTableIsQueryable:
    def test_accepts_rows_belonging_to_the_table(self):
        m = _import_software_steps()
        output = "documents\tcfa284ff\torg.mozilla.firefox\tread,write\t()\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            m.flatpak_permissions_table_is_queryable(MagicMock(), "documents")

    def test_rejects_rows_from_another_table(self):
        m = _import_software_steps()
        output = "background\tbackground\torg.mozilla.firefox\tyes\t0x00\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            with pytest.raises(AssertionError, match="do not belong to"):
                m.flatpak_permissions_table_is_queryable(MagicMock(), "documents")

    def test_rejects_non_row_banner_output(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="error: unknown table\n", rc=0)):
            with pytest.raises(AssertionError, match="do not belong to"):
                m.flatpak_permissions_table_is_queryable(MagicMock(), "documents")

    def test_raises_on_unexpected_failure(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=1, stderr="boom")):
            with pytest.raises(AssertionError, match="failed unexpectedly"):
                m.flatpak_permissions_table_is_queryable(MagicMock(), "documents")


# ---------------------------------------------------------------------------
# flatpak_documents_portal_reports_mount_point
# ---------------------------------------------------------------------------

class TestFlatpakDocumentsPortalReportsMountPoint:
    """The non-vacuous existence proof for the `documents` table.

    `flatpak permissions <table>` exits 0 with empty output for a nonexistent
    table, so only the portal's own GetMountPoint call can fail when the
    documents backend is absent.
    """

    def test_passes_when_mount_point_is_returned(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session",
                          return_value=_completed(stdout="(b'/run/user/1000/doc',)\n", rc=0)):
            m.flatpak_documents_portal_reports_mount_point(MagicMock())

    def test_raises_when_portal_is_absent(self):
        m = _import_software_steps()
        stdout = "Error: GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown\n"
        with patch.object(m, "_run_in_session", return_value=_completed(stdout=stdout, rc=0)):
            with pytest.raises(AssertionError, match="did not return a"):
                m.flatpak_documents_portal_reports_mount_point(MagicMock())

    def test_raises_on_empty_output(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed(stdout="", rc=0)):
            with pytest.raises(AssertionError, match="did not return a"):
                m.flatpak_documents_portal_reports_mount_point(MagicMock())

    def test_raises_when_command_fails(self):
        m = _import_software_steps()
        with patch.object(m, "_run_in_session", return_value=_completed(stdout="", rc=1, stderr="x")):
            with pytest.raises(AssertionError, match="Could not reach the documents portal"):
                m.flatpak_documents_portal_reports_mount_point(MagicMock())
