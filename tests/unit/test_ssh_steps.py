"""Unit tests for tests/shared/ssh_steps.py.

Tests run_ssh command construction (prefix injection, port handling,
context attribute setting) using subprocess mocks. No live SSH required.
"""

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper — build a minimal behave context mock
# ---------------------------------------------------------------------------

def _make_context(*, ssh_key="/tmp/test.key", ssh_user="bluefin-test",
                  vm_ip="192.168.1.5", ssh_port=None, ssh_command_prefix=""):
    ctx = MagicMock()
    ctx.ssh_key = ssh_key
    ctx.ssh_user = ssh_user
    ctx.vm_ip = vm_ip
    ctx.ssh_port = ssh_port
    ctx.ssh_command_prefix = ssh_command_prefix
    ctx.command_stdout = ""
    ctx.last_command_output = ""
    ctx.ssh_rc = None
    ctx.last_ssh_result = None
    # run_ssh resolves connection details via tests.shared.ssh_config, which
    # reads context.config.userdata (a real dict) after context attributes —
    # a bare MagicMock here would auto-fabricate a truthy userdata.get(...)
    # result and corrupt resolution.
    ctx.config = types.SimpleNamespace(userdata={})
    return ctx


def _make_proc(stdout="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Import helper (avoids behave decorator side effects)
# ---------------------------------------------------------------------------

def _import_ssh_steps():
    import sys
    behave_stub = MagicMock()
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules.setdefault("behave", behave_stub)
    sys.modules.setdefault("behave.runner", MagicMock())

    if "tests.shared.ssh_steps" in sys.modules:
        del sys.modules["tests.shared.ssh_steps"]

    import tests.shared.ssh_steps as m
    return m


# ---------------------------------------------------------------------------
# run_ssh — basic functionality
# ---------------------------------------------------------------------------

class TestRunSsh:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_returns_stdout_and_returncode(self):
        ctx = _make_context()
        proc = _make_proc(stdout="hello\n", returncode=0)
        with patch("subprocess.run", return_value=proc):
            stdout, rc = self.mod.run_ssh(ctx, "echo hello")
        assert stdout == "hello"   # .strip() applied
        assert rc == 0

    def test_sets_context_attributes(self):
        ctx = _make_context()
        proc = _make_proc(stdout="output\n", returncode=0)
        with patch("subprocess.run", return_value=proc):
            self.mod.run_ssh(ctx, "somecommand")
        assert ctx.command_stdout == "output"
        assert ctx.last_command_output == "output"
        assert ctx.ssh_rc == 0
        assert ctx.last_ssh_result is proc

    def test_includes_ssh_key_in_command(self):
        ctx = _make_context(ssh_key="/home/user/.ssh/id_rsa")
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo ok")
        call_args = mock_run.call_args[0][0]
        assert "/home/user/.ssh/id_rsa" in call_args

    def test_no_prefix_passes_command_directly(self):
        ctx = _make_context(ssh_command_prefix="")
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo direct")
        call_args = mock_run.call_args[0][0]
        # The raw command should be the last element
        assert call_args[-1] == "echo direct"

    def test_prefix_wraps_in_bash_c(self):
        ctx = _make_context(ssh_command_prefix="export VAR=1")
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo wrapped")
        call_args = mock_run.call_args[0][0]
        # The prefix+command is embedded in the final SSH argument as "bash -c '...'"
        last_arg = call_args[-1]
        assert "bash" in last_arg
        assert "-c" in last_arg
        assert "-lc" not in last_arg
        assert "export VAR=1" in last_arg
        assert "echo wrapped" in last_arg

    def test_embedded_python_command_passed_verbatim(self):
        """Regression for issue #531's immutable-suite shell quoting."""
        ctx = _make_context()
        proc = _make_proc(stdout="0\n", returncode=0)
        command = (
            "rpm-ostree status --json | python3 -c $'"
            'import sys,json; d=json.load(sys.stdin); '
            'print(len([p for dep in d.get(\\"deployments\\",[]) '
            'for p in dep.get(\\"requested-packages\\",[])]))'
            "'"
        )
        with patch("subprocess.run", return_value=proc) as mock_run:
            stdout, rc = self.mod.run_ssh(ctx, command)
        assert mock_run.call_args.args[0][-1] == command
        assert "python3 -c $'" in mock_run.call_args.args[0][-1]
        assert '\\"' in mock_run.call_args.args[0][-1]
        assert stdout == "0"
        assert rc == 0

    def test_ansi_c_python_command_survives_prefix_wrapping(self):
        """The immutable quoting fix must survive optional command prefixes."""
        ctx = _make_context(ssh_command_prefix="export TEST_MODE=1")
        proc = _make_proc(stdout="0\n", returncode=0)
        command = (
            "bootc status --json | python3 -c $'"
            'import sys,json; d=json.load(sys.stdin); '
            'print(d.get(\\"status\\", {}).get(\\"booted\\", {}))'
            "'"
        )
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, command)
        final_arg = mock_run.call_args.args[0][-1]
        assert "export TEST_MODE=1; " in final_arg
        assert command.replace("'", "'\"'\"'") in final_arg

    def test_ssh_port_included_when_set(self):
        ctx = _make_context(ssh_port=2222)
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo ok")
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert "2222" in call_args

    def test_default_port_used_when_ssh_port_is_none(self):
        """ssh_argv() always emits an explicit -p; unset context.ssh_port
        resolves to ssh_config.DEFAULT_SSH_PORT ("22"), matching the ssh
        default rather than omitting the flag."""
        ctx = _make_context(ssh_port=None)
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo ok")
        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        assert call_args[call_args.index("-p") + 1] == "22"

    def test_target_host_in_command(self):
        ctx = _make_context(ssh_user="testuser", vm_ip="10.0.0.5")
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo ok")
        call_args = mock_run.call_args[0][0]
        assert "testuser@10.0.0.5" in call_args

    def test_strict_host_checking_disabled(self):
        ctx = _make_context()
        proc = _make_proc(stdout="ok\n")
        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.run_ssh(ctx, "echo ok")
        call_args = mock_run.call_args[0][0]
        assert "StrictHostKeyChecking=no" in call_args

    def test_local_target_runs_subprocess_directly(self):
        ctx = _make_context(vm_ip="")
        proc = _make_proc(stdout="local output\n", returncode=0)
        with patch("subprocess.run", return_value=proc) as mock_run:
            stdout, rc = self.mod.run_ssh(ctx, "echo local")
        assert stdout == "local output"
        assert rc == 0
        mock_run.assert_called_once_with(
            ["bash", "-c", "echo local"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_local_target_with_bootc_binary_runs_locally(self):
        ctx = _make_context(vm_ip="127.0.0.1")
        proc = _make_proc(stdout="bootc ok\n", returncode=0)
        with patch("os.path.isfile", return_value=True), patch("subprocess.run", return_value=proc) as mock_run:
            stdout, rc = self.mod.run_ssh(ctx, "bootc status")
        assert stdout == "bootc ok"
        assert rc == 0
        mock_run.assert_called_once_with(
            ["bash", "-c", "bootc status"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_nonzero_returncode_stored_on_context(self):
        ctx = _make_context()
        proc = _make_proc(stdout="", returncode=1)
        with patch("subprocess.run", return_value=proc):
            _, rc = self.mod.run_ssh(ctx, "false")
        assert rc == 1
        assert ctx.ssh_rc == 1


# ---------------------------------------------------------------------------
# vm_reachable_over_ssh — retry behaviour
# ---------------------------------------------------------------------------

class TestVmReachableOverSsh:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_succeeds_immediately_when_local_target(self):
        ctx = _make_context(vm_ip="")
        # Should not call run_ssh or sleep at all
        with patch.object(self.mod, "run_ssh") as mock_run:
            self.mod.vm_reachable_over_ssh(ctx)
            mock_run.assert_not_called()

    def test_succeeds_immediately_when_ssh_works(self):
        ctx = _make_context()
        with patch.object(self.mod, "run_ssh", return_value=("ok", 0)):
            with patch("tests.shared.ssh_steps.sleep"):
                # Should not raise
                self.mod.vm_reachable_over_ssh(ctx)

    def test_retries_then_succeeds(self):
        ctx = _make_context()
        side_effects = [
            ("", 1),
            ("", 1),
            ("ok", 0),
        ]
        call_count = {"n": 0}

        def _mock_run_ssh(context, cmd, timeout=20):
            val = side_effects[call_count["n"]]
            call_count["n"] += 1
            return val

        with patch.object(self.mod, "run_ssh", side_effect=_mock_run_ssh):
            with patch("tests.shared.ssh_steps.sleep"):
                self.mod.vm_reachable_over_ssh(ctx)
        assert call_count["n"] == 3

    def test_raises_after_all_retries_fail(self):
        ctx = _make_context()
        with patch.object(self.mod, "run_ssh", return_value=("", 1)):
            with patch("tests.shared.ssh_steps.sleep"):
                with pytest.raises(Exception):
                    self.mod.vm_reachable_over_ssh(ctx)


class TestSshOutputNotValues:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_passes_when_output_is_neither_value(self):
        ctx = _make_context()
        ctx.command_stdout = " ready \n"

        self.mod.ssh_output_not_values(ctx, "offline", "failed")

    def test_raises_when_output_matches_forbidden_value(self):
        ctx = _make_context()
        ctx.command_stdout = "failed\n"

        with pytest.raises(AssertionError, match="expected neither 'offline' nor 'failed'"):
            self.mod.ssh_output_not_values(ctx, "offline", "failed")


class TestSshOutputDoesNotContain:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_passes_when_text_is_absent(self):
        ctx = _make_context()
        ctx.command_stdout = "all systems nominal\n"

        self.mod.ssh_output_does_not_contain(ctx, "error")

    def test_raises_when_text_is_present(self):
        ctx = _make_context()
        ctx.command_stdout = "fatal error: something broke\n"

        with pytest.raises(AssertionError, match="contains 'error'"):
            self.mod.ssh_output_does_not_contain(ctx, "error")


class TestLastCommandOutputContains:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_prefers_command_stdout_when_present(self):
        ctx = _make_context()
        ctx.command_stdout = "latest output"
        ctx.last_command_output = "older output"
        ctx.last_run_output = "oldest output"

        self.mod.last_command_output_contains(ctx, "latest")

    def test_falls_back_to_last_run_output(self):
        ctx = _make_context()
        ctx.command_stdout = ""
        ctx.last_command_output = ""
        ctx.last_run_output = "fallback output"

        self.mod.last_command_output_contains(ctx, "fallback")

    def test_raises_when_text_is_missing(self):
        ctx = _make_context()
        ctx.command_stdout = "hello world"

        with pytest.raises(AssertionError, match="does not contain 'missing'"):
            self.mod.last_command_output_contains(ctx, "missing")


class TestNoJournalEntriesMatch:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_passes_when_journalctl_finds_no_matches(self):
        ctx = _make_context()
        proc = _make_proc(stdout="", returncode=1)
        proc.stderr = ""

        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.no_journal_entries_match(ctx, "gnome-shell")

        mock_run.assert_called_once_with(
            ["journalctl", "-b", "--no-pager", "-g", "gnome-shell"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_raises_when_journal_entries_match(self):
        ctx = _make_context()
        proc = _make_proc(stdout="matched log line\n", returncode=0)
        proc.stderr = ""

        with patch("subprocess.run", return_value=proc):
            with pytest.raises(AssertionError, match="Unexpected journal entries matched"):
                self.mod.no_journal_entries_match(ctx, "gnome-shell")

    def test_raises_when_journalctl_errors(self):
        ctx = _make_context()
        proc = _make_proc(stdout="", returncode=2)
        proc.stderr = "permission denied"

        with patch("subprocess.run", return_value=proc):
            with pytest.raises(AssertionError, match="journalctl failed"):
                self.mod.no_journal_entries_match(ctx, "gnome-shell")


class TestNoCoredumpEntriesExist:
    def setup_method(self):
        self.mod = _import_ssh_steps()

    def test_passes_when_coredumpctl_has_no_matching_entries(self):
        ctx = _make_context()
        proc = _make_proc(stdout="", returncode=1)
        proc.stderr = ""

        with patch("subprocess.run", return_value=proc) as mock_run:
            self.mod.no_coredump_entries_exist(ctx, "gnome-shell")

        mock_run.assert_called_once_with(
            ["coredumpctl", "list", "gnome-shell", "--no-pager", "--lines=10"],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_raises_when_named_coredump_entry_exists(self):
        ctx = _make_context()
        proc = _make_proc(stdout="Fri gnome-shell 1234\nFri another 5678\n", returncode=0)
        proc.stderr = ""

        with patch("subprocess.run", return_value=proc):
            with pytest.raises(AssertionError, match="Unexpected coredump entries for gnome-shell"):
                self.mod.no_coredump_entries_exist(ctx, "gnome-shell")

    def test_raises_when_coredumpctl_errors(self):
        ctx = _make_context()
        proc = _make_proc(stdout="", returncode=2)
        proc.stderr = "failed"

        with patch("subprocess.run", return_value=proc):
            with pytest.raises(AssertionError, match="coredumpctl failed"):
                self.mod.no_coredump_entries_exist(ctx, "gnome-shell")
