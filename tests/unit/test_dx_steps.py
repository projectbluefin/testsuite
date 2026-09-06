"""Unit tests for tests/dx/features/steps/steps.py assertion helpers."""
import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_dx_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    for key in list(sys.modules):
        if "dx.features.steps.steps" in key:
            del sys.modules[key]

    import tests.dx.features.steps.steps as m  # noqa: PLC0415
    return m


def _ctx(**kwargs):
    """Build a minimal behave context mock with the given attributes."""
    ctx = MagicMock()
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# ssh_return_code_is
# ---------------------------------------------------------------------------

class TestSshReturnCodeIs:
    def test_passes_when_codes_match(self):
        m = _import_dx_steps()
        ctx = _ctx(ssh_rc=0, command_stdout="ok", last_ssh_result=None)
        m.ssh_return_code_is(ctx, "0")  # should not raise

    def test_raises_when_codes_differ(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(ssh_rc=1, command_stdout="err", last_ssh_result=None)
        with pytest.raises(AssertionError, match="Expected SSH return code 0"):
            m.ssh_return_code_is(ctx, "0")

    def test_matches_nonzero_code(self):
        m = _import_dx_steps()
        ctx = _ctx(ssh_rc=42, command_stdout="", last_ssh_result=None)
        m.ssh_return_code_is(ctx, "42")  # should not raise

    def test_includes_stdout_in_error_message(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(ssh_rc=2, command_stdout="some output", last_ssh_result=None)
        with pytest.raises(AssertionError, match="some output"):
            m.ssh_return_code_is(ctx, "0")


# ---------------------------------------------------------------------------
# ssh_output_is
# ---------------------------------------------------------------------------

class TestSshOutputIs:
    def test_passes_on_exact_match(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="hello")
        m.ssh_output_is(ctx, "hello")  # should not raise

    def test_raises_on_mismatch(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(command_stdout="hello world")
        with pytest.raises(AssertionError, match="Expected"):
            m.ssh_output_is(ctx, "hello")

    def test_strips_whitespace_before_comparing(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="  hello  ")
        m.ssh_output_is(ctx, "hello")  # should not raise

    def test_raises_on_empty_vs_nonempty(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(command_stdout="data")
        with pytest.raises(AssertionError):
            m.ssh_output_is(ctx, "")

    def test_handles_missing_command_stdout(self):
        m = _import_dx_steps()
        import pytest
        ctx = MagicMock(spec=[])  # no attributes
        with pytest.raises(AssertionError):
            m.ssh_output_is(ctx, "expected")


# ---------------------------------------------------------------------------
# output_does_not_contain
# ---------------------------------------------------------------------------

class TestOutputDoesNotContain:
    def test_passes_when_text_absent(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="hello world")
        m.output_does_not_contain(ctx, "error")  # should not raise

    def test_raises_when_text_present(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(command_stdout="fatal error occurred")
        with pytest.raises(AssertionError, match="unexpectedly contains"):
            m.output_does_not_contain(ctx, "error")

    def test_passes_on_empty_output(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="")
        m.output_does_not_contain(ctx, "error")  # should not raise

    def test_handles_none_output(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout=None)
        m.output_does_not_contain(ctx, "error")  # should not raise (None treated as "")


# ---------------------------------------------------------------------------
# output_contains
# ---------------------------------------------------------------------------

class TestOutputContains:
    def test_passes_when_text_present(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="hello world")
        m.output_contains(ctx, "world")  # should not raise

    def test_raises_when_text_absent(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(command_stdout="hello")
        with pytest.raises(AssertionError, match="does not contain"):
            m.output_contains(ctx, "world")

    def test_partial_match_passes(self):
        m = _import_dx_steps()
        ctx = _ctx(command_stdout="the quick brown fox")
        m.output_contains(ctx, "quick")  # should not raise

    def test_handles_none_output(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ctx(command_stdout=None)
        with pytest.raises(AssertionError):
            m.output_contains(ctx, "something")


# ---------------------------------------------------------------------------
# _wait_until helper in developer suite
# ---------------------------------------------------------------------------

def _import_developer_steps():
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
        if "developer.features.steps.steps" in key:
            del sys.modules[key]

    import tests.developer.features.steps.steps as m  # noqa: PLC0415
    return m


class TestWaitUntil:
    def test_returns_immediately_when_predicate_true(self):
        m = _import_developer_steps()
        result = m._wait_until("should pass", lambda: 42, timeout=5)
        assert result == 42

    def test_raises_assertion_error_on_timeout(self):
        m = _import_developer_steps()
        import pytest
        with pytest.raises(AssertionError, match="timed out"):
            m._wait_until("timed out", lambda: False, timeout=0)

    def test_returns_truthy_value(self):
        m = _import_developer_steps()
        result = m._wait_until("ok", lambda: "hello", timeout=5)
        assert result == "hello"

    def test_ui_timeout_constant_is_positive(self):
        m = _import_developer_steps()
        assert m.UI_TIMEOUT_SECONDS > 0


# ---------------------------------------------------------------------------
# dx_distrobox_installs_package / dx_distrobox_exports_binary_to_host (#501)
# ---------------------------------------------------------------------------

def _make_ssh_proc(stdout="", rc=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = rc
    return proc


class _FakeSSH:
    """Patches subprocess.run inside the dx steps module and serves canned
    results per invocation, in order."""

    def __init__(self, module, results):
        self.module = module
        self.results = list(results)
        self.calls = []
        import unittest.mock as um
        self._patcher = um.patch("subprocess.run", side_effect=self._run)

    def _run(self, args, **kwargs):
        self.calls.append(args)
        if not self.results:
            raise AssertionError("unexpected extra SSH call")
        return self.results.pop(0)

    def __enter__(self):
        self._patcher.start()
        return self

    def __exit__(self, *exc):
        self._patcher.stop()


def _ssh_ctx():
    return _ctx(
        ssh_key="/tmp/key",
        ssh_user="bluefin-test",
        vm_ip="127.0.0.1",
        command_stdout="",
        last_command_output="",
        ssh_rc=None,
        last_ssh_result=None,
    )


class TestDistroboxInstallsPackage:
    def test_happy_path_installs_and_verifies(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        # 1) dnf install rc=0  2) which htop rc=0
        with _FakeSSH(m, [_make_ssh_proc("installed", 0), _make_ssh_proc("/usr/bin/htop", 0)]):
            m.dx_distrobox_installs_package(ctx, "test-box", "htop")

    def test_raises_when_dnf_install_fails(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("Error: no match", 1)]):
            with pytest.raises(AssertionError, match="dnf install"):
                m.dx_distrobox_installs_package(ctx, "test-box", "htop")

    def test_raises_when_binary_missing_after_install(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("installed", 0), _make_ssh_proc("", 1)]):
            with pytest.raises(AssertionError, match="not on PATH"):
                m.dx_distrobox_installs_package(ctx, "test-box", "htop")

    def test_ssh_command_uses_distrobox_enter(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("installed", 0), _make_ssh_proc("/usr/bin/htop", 0)]) as ssh:
            m.dx_distrobox_installs_package(ctx, "test-box", "htop")
        assert any("distrobox enter --name test-box -- sudo dnf install -y htop" == c[-1] for c in ssh.calls)


class TestDistroboxExportsBinaryToHost:
    def test_happy_path_exports_and_verifies(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        # 1) distrobox-export rc=0  2) ls rc=0
        with _FakeSSH(m, [_make_ssh_proc("exported", 0), _make_ssh_proc("/var/home/bluefin-test/.local/bin/htop", 0)]):
            m.dx_distrobox_exports_binary_to_host(ctx, "test-box", "/usr/bin/htop")

    def test_raises_when_export_fails(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("no such binary", 1)]):
            with pytest.raises(AssertionError, match="distrobox-export"):
                m.dx_distrobox_exports_binary_to_host(ctx, "test-box", "/usr/bin/htop")

    def test_raises_when_exported_file_missing_on_host(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("exported", 0), _make_ssh_proc("", 1)]):
            with pytest.raises(AssertionError, match="not found in ~/.local/bin"):
                m.dx_distrobox_exports_binary_to_host(ctx, "test-box", "/usr/bin/htop")

    def test_export_command_targets_host_local_bin(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("exported", 0), _make_ssh_proc("ok", 0)]) as ssh:
            m.dx_distrobox_exports_binary_to_host(ctx, "test-box", "/usr/bin/htop")
        export_cmd = ssh.calls[0][-1]
        assert "distrobox-export --bin /usr/bin/htop --export-path ~/.local/bin" in export_cmd


# ---------------------------------------------------------------------------
# dx_distrobox_can_be_created (#501)
# ---------------------------------------------------------------------------


class TestDistroboxCanBeCreated:
    """Unit tests for dx_distrobox_can_be_created.

    The step makes three sequential SSH calls:
      1. ``distrobox rm --force <name>``  — cleanup; rc 0 or 1 (or "No such
         container" in output) are both acceptable.
      2. ``distrobox create --name <name> --image <image> --yes``  — create.
      3. ``distrobox list --no-color``  — verify the name appears in the output.
    """

    def test_happy_path_creates_and_verifies(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        # 1) rm rc=0  2) create rc=0  3) list rc=0 with name in output
        with _FakeSSH(m, [
            _make_ssh_proc("", 0),
            _make_ssh_proc("", 0),
            _make_ssh_proc("test-box  registry.fedoraproject.org/fedora-toolbox:latest", 0),
        ]):
            m.dx_distrobox_can_be_created(
                ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
            )

    def test_cleanup_rc_1_is_acceptable(self):
        """rc=1 from distrobox rm means the container was not found — not an error."""
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        with _FakeSSH(m, [
            _make_ssh_proc("", 1),
            _make_ssh_proc("", 0),
            _make_ssh_proc("test-box  registry.fedoraproject.org/fedora-toolbox:latest", 0),
        ]):
            m.dx_distrobox_can_be_created(
                ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
            )

    def test_cleanup_no_such_container_text_is_acceptable(self):
        """Any rc is acceptable when the output contains 'No such container'."""
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        with _FakeSSH(m, [
            _make_ssh_proc("Error: No such container: test-box", 2),
            _make_ssh_proc("", 0),
            _make_ssh_proc("test-box  registry.fedoraproject.org/fedora-toolbox:latest", 0),
        ]):
            m.dx_distrobox_can_be_created(
                ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
            )

    def test_cleanup_unexpected_rc_raises(self):
        """Unexpected cleanup failure (non-0/1 rc, no 'No such container') raises."""
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("Connection refused", 2)]):
            with pytest.raises(AssertionError, match="Unexpected distrobox cleanup failure"):
                m.dx_distrobox_can_be_created(
                    ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
                )

    def test_raises_when_create_fails(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [_make_ssh_proc("", 0), _make_ssh_proc("Error: image not found", 1)]):
            with pytest.raises(AssertionError, match="distrobox create failed"):
                m.dx_distrobox_can_be_created(
                    ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
                )

    def test_raises_when_list_fails(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [
            _make_ssh_proc("", 0),
            _make_ssh_proc("", 0),
            _make_ssh_proc("", 1),
        ]):
            with pytest.raises(AssertionError, match="distrobox list failed"):
                m.dx_distrobox_can_be_created(
                    ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
                )

    def test_raises_when_name_not_in_list(self):
        m = _import_dx_steps()
        import pytest
        ctx = _ssh_ctx()
        with _FakeSSH(m, [
            _make_ssh_proc("", 0),
            _make_ssh_proc("", 0),
            _make_ssh_proc("other-box  registry.fedoraproject.org/fedora-toolbox:latest", 0),
        ]):
            with pytest.raises(AssertionError, match="not found after create"):
                m.dx_distrobox_can_be_created(
                    ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
                )

    def test_create_command_uses_yes_flag_and_named_image(self):
        m = _import_dx_steps()
        ctx = _ssh_ctx()
        with _FakeSSH(m, [
            _make_ssh_proc("", 0),
            _make_ssh_proc("", 0),
            _make_ssh_proc("test-box  registry.fedoraproject.org/fedora-toolbox:latest", 0),
        ]) as ssh:
            m.dx_distrobox_can_be_created(
                ctx, "test-box", "registry.fedoraproject.org/fedora-toolbox:latest"
            )
        create_cmd = ssh.calls[1][-1]
        assert "--name test-box" in create_cmd
        assert "--image registry.fedoraproject.org/fedora-toolbox:latest" in create_cmd
        assert "--yes" in create_cmd
