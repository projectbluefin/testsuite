"""Unit tests for tests/smoke/features/steps/sudo_rs_steps.py.

The module asserts sudo-rs setuid mode, ownership, PAM wiring and sudoedit
health inside a live VM, so ``behave`` and the ``steps.steps._run_host``
transport are stubbed and only the assertion logic is exercised.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest


def _import_sudo_rs_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    steps_pkg = types.ModuleType("steps")
    steps_mod = types.ModuleType("steps.steps")
    steps_mod._run_host = MagicMock()
    steps_pkg.steps = steps_mod
    sys.modules["steps"] = steps_pkg
    sys.modules["steps.steps"] = steps_mod

    sys.modules.pop("tests.smoke.features.steps.sudo_rs_steps", None)

    import tests.smoke.features.steps.sudo_rs_steps as m  # noqa: PLC0415
    return m


@pytest.fixture
def mod():
    return _import_sudo_rs_steps()


def _responses(mod, *results):
    mod._run_host.reset_mock()
    mod._run_host.side_effect = list(results)


class TestSudoIsSetuidRoot:
    def test_passes_on_4755_root_root(self, mod):
        _responses(mod, ("4755 root:root", 0, ""))

        mod.sudo_is_setuid_root_4755(MagicMock())

        assert mod._run_host.call_args[0][0] == "stat -c '%a %U:%G' /usr/bin/sudo"

    def test_fails_when_stat_returns_nonzero(self, mod):
        _responses(mod, ("", 1, "No such file"))

        with pytest.raises(AssertionError, match="stat on /usr/bin/sudo failed"):
            mod.sudo_is_setuid_root_4755(MagicMock())

    def test_fails_when_setuid_bit_stripped(self, mod):
        _responses(mod, ("755 root:root", 0, ""))

        with pytest.raises(AssertionError, match="invalid mode '755'"):
            mod.sudo_is_setuid_root_4755(MagicMock())

    def test_fails_when_owner_is_not_root(self, mod):
        _responses(mod, ("4755 bin:bin", 0, ""))

        with pytest.raises(AssertionError, match="owner is 'bin:bin'"):
            mod.sudo_is_setuid_root_4755(MagicMock())


class TestSudoNIdU:
    def test_passes_when_non_root_escalates_to_uid_0(self, mod):
        _responses(mod, ("1000", 0, ""), ("0", 0, ""))

        mod.sudo_n_id_u_returns_0(MagicMock())

        assert [c[0][0] for c in mod._run_host.call_args_list] == [
            "id -u",
            "sudo -n id -u",
        ]

    def test_fails_when_id_u_errors(self, mod):
        _responses(mod, ("", 1, "boom"))

        with pytest.raises(AssertionError, match="id -u failed"):
            mod.sudo_n_id_u_returns_0(MagicMock())

    def test_fails_when_already_root(self, mod):
        _responses(mod, ("0", 0, ""))

        with pytest.raises(AssertionError, match="must start as a non-root user"):
            mod.sudo_n_id_u_returns_0(MagicMock())

    def test_fails_when_sudo_returns_nonzero(self, mod):
        _responses(mod, ("1000", 0, ""), ("", 1, "not allowed"))

        with pytest.raises(AssertionError, match=r"sudo -n id -u failed \(rc=1\)"):
            mod.sudo_n_id_u_returns_0(MagicMock())

    def test_fails_when_escalated_uid_is_not_zero(self, mod):
        _responses(mod, ("1000", 0, ""), ("1000", 0, ""))

        with pytest.raises(AssertionError, match="Expected root UID 0"):
            mod.sudo_n_id_u_returns_0(MagicMock())


class TestSudoPreserveEnv:
    def test_passes_when_preserved_kept_and_other_scrubbed(self, mod):
        _responses(mod, ("PATH=/usr/bin\nTEST_SUDO_PRESERVED=kept", 0, ""))

        mod.sudo_preserve_env_check(MagicMock())

        cmd = mod._run_host.call_args[0][0]
        assert "--preserve-env=TEST_SUDO_PRESERVED" in cmd

    def test_fails_when_command_errors(self, mod):
        _responses(mod, ("", 1, "sudo: unknown option"))

        with pytest.raises(AssertionError, match="--preserve-env execution failed"):
            mod.sudo_preserve_env_check(MagicMock())

    def test_fails_when_preserved_variable_dropped(self, mod):
        _responses(mod, ("PATH=/usr/bin", 0, ""))

        with pytest.raises(AssertionError, match="TEST_SUDO_PRESERVED to be retained"):
            mod.sudo_preserve_env_check(MagicMock())

    def test_fails_when_scrubbed_variable_leaks(self, mod):
        _responses(
            mod,
            ("TEST_SUDO_PRESERVED=kept\nTEST_SUDO_SCRUBBED=secret", 0, ""),
        )

        with pytest.raises(AssertionError, match="TEST_SUDO_SCRUBBED to be scrubbed"):
            mod.sudo_preserve_env_check(MagicMock())


class TestSudoPamIncludesSystemAuth:
    def test_passes_when_grep_matches(self, mod):
        _responses(mod, ("", 0, ""))

        mod.sudo_pam_includes_system_auth(MagicMock())

        assert "/etc/pam.d/sudo" in mod._run_host.call_args[0][0]

    def test_fails_when_grep_finds_nothing(self, mod):
        _responses(mod, ("", 1, ""))

        with pytest.raises(AssertionError, match="does not include the system-auth stack"):
            mod.sudo_pam_includes_system_auth(MagicMock())


class TestSudoeditBinaryCheck:
    def test_passes_on_healthy_sudoedit(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("4755 root:root", 0, ""),
            ("sudo-rs 0.2.6", 0, ""),
        )

        mod.sudoedit_binary_check(MagicMock())

        assert len(mod._run_host.call_args_list) == 3

    def test_stat_follows_sudoedit_symlink(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("4755 root:root", 0, ""),
            ("sudo-rs 0.2.6", 0, ""),
        )

        mod.sudoedit_binary_check(MagicMock())

        assert mod._run_host.call_args_list[1][0][0].startswith("stat -L ")

    def test_fails_when_binary_missing(self, mod):
        _responses(mod, ("", 1, "not found"))

        with pytest.raises(AssertionError, match="sudoedit binary not found on PATH"):
            mod.sudoedit_binary_check(MagicMock())

    def test_fails_when_stat_errors(self, mod):
        _responses(mod, ("/usr/bin/sudoedit", 0, ""), ("", 1, "stat: boom"))

        with pytest.raises(AssertionError, match="stat sudoedit failed"):
            mod.sudoedit_binary_check(MagicMock())

    def test_fails_when_mode_is_not_setuid(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("0755 root:root", 0, ""),
        )

        with pytest.raises(AssertionError, match="sudoedit has invalid mode '0755'"):
            mod.sudoedit_binary_check(MagicMock())

    def test_fails_when_owner_is_not_root(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("4755 root:wheel", 0, ""),
        )

        with pytest.raises(AssertionError, match=r"sudoedit owner is 'root:wheel'"):
            mod.sudoedit_binary_check(MagicMock())

    def test_fails_when_version_command_errors(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("4755 root:root", 0, ""),
            ("", 1, "segfault"),
        )

        with pytest.raises(AssertionError, match="sudoedit -V failed"):
            mod.sudoedit_binary_check(MagicMock())

    def test_fails_when_version_output_is_empty(self, mod):
        _responses(
            mod,
            ("/usr/bin/sudoedit", 0, ""),
            ("4755 root:root", 0, ""),
            ("", 0, ""),
        )

        with pytest.raises(AssertionError, match="returned no version information"):
            mod.sudoedit_binary_check(MagicMock())
