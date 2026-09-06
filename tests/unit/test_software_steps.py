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
    # A stub missing run_ssh permanently corrupts this sys.modules entry for
    # every later test in this xdist worker (e.g. test_installer_environment.py
    # monkeypatching ssh_steps.run_ssh), so keep the attribute present.
    ssh_steps_stub.run_ssh = MagicMock(return_value=("", 0))
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
        with patch.object(m, "_bazaar_window", side_effect=RuntimeError), \
             patch.object(m, "_bazaar_flatpak_is_running", return_value=False) as running:
            m._wait_for_bazaar_to_close(ctx)
        running.assert_called_once_with(ctx)


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
# flatpak_user_override_is_active — fragment assertion
# ---------------------------------------------------------------------------

class TestFlatpakUserOverrideIsActive:
    def test_passes_when_fragment_in_output(self):
        m = _import_software_steps()
        with patch.object(m, "_flatpak", return_value=_completed(stdout="--filesystem=home", rc=0)):
            ctx = MagicMock()
            m.flatpak_user_override_is_active(ctx, "--filesystem=home", "myapp")

    def test_raises_when_fragment_missing(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="[Context]", rc=0)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="not found"):
                m.flatpak_user_override_is_active(ctx, "--filesystem=home", "myapp")

    def test_raises_on_nonzero_rc(self):
        m = _import_software_steps()
        import pytest
        with patch.object(m, "_flatpak", return_value=_completed(stdout="", rc=1)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="failed"):
                m.flatpak_user_override_is_active(ctx, "--filesystem=home", "myapp")


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

    def test_case_insensitive_remote_match(self):
        m = _import_software_steps()
        output = "Application ID: io.github.kolunmi.Bazaar\nOrigin: FLATHUB\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            ctx = MagicMock()
            m.flatpak_app_is_from_remote(ctx, "io.github.kolunmi.Bazaar", "flathub")

    def test_raises_when_remote_missing(self):
        m = _import_software_steps()
        import pytest
        output = "Application ID: io.github.kolunmi.Bazaar\nOrigin: sideload\n"
        with patch.object(m, "_flatpak", return_value=_completed(stdout=output, rc=0)):
            ctx = MagicMock()
            with pytest.raises(AssertionError, match="not found"):
                m.flatpak_app_is_from_remote(ctx, "io.github.kolunmi.Bazaar", "flathub")

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
