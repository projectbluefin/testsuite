"""Contract tests for the shared SSH transport builder.

``tests/shared/ssh_config.ssh_argv`` is the single place where SSH transport
policy (host-key handling, connect timeout, port flag, destination) is
expressed. These tests pin that behaviour and guard the modules that were
migrated onto it against re-growing a private copy of the argv.
"""

import os
import pathlib
from unittest.mock import patch

import tests.shared.ssh_config as ssh_config


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Modules migrated onto ssh_config.ssh_argv(). Any new raw `ssh` argv here is a
# regression: the transport policy must stay in tests/shared/ssh_config.py.
MIGRATED_MODULES = (
    "tests/shared/gnome_shell_steps.py",
    "tests/shared/ssh_steps.py",
    "tests/shared/image_cache.py",
    "tests/shared/screenshot.py",
    "tests/smoke/features/steps/app_support.py",
    "tests/smoke/features/steps/display_scaling_steps.py",
    "tests/smoke/features/steps/gnome_apps_steps.py",
    "tests/smoke/features/steps/gnome_extensions_steps.py",
    "tests/smoke/features/steps/gnome_notifications_steps.py",
    "tests/smoke/features/steps/steps.py",
    "tests/smoke/features/steps/system_health_steps.py",
    "tests/dx/features/steps/steps.py",
    "tests/flatcar/features/steps/steps.py",
    "tests/kde-smoke/features/steps/steps.py",
    "tests/software/features/steps/steps.py",
    "tests/software/features/environment.py",
    "tests/vanilla-gnome/features/steps/steps.py",
)


def _clean_env(**overrides):
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("SSH_KEY", "SSH_KEY_PATH", "VM_IP", "VM_USER", "SSH_USER",
                     "SSH_PORT", "VM_PORT")
    }
    env.update(overrides)
    return env


class TestSshArgv:
    def test_starts_with_ssh(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            assert ssh_config.ssh_argv()[0] == "ssh"

    def test_defaults_when_nothing_configured(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            argv = ssh_config.ssh_argv()
        assert ssh_config.DEFAULT_SSH_KEY in argv
        assert f"{ssh_config.DEFAULT_VM_USER}@{ssh_config.DEFAULT_VM_IP}" in argv
        assert argv[argv.index("-p") + 1] == ssh_config.DEFAULT_SSH_PORT

    def test_disables_host_key_prompts(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            argv = ssh_config.ssh_argv()
        assert "StrictHostKeyChecking=no" in argv
        assert "UserKnownHostsFile=/dev/null" in argv

    def test_reads_environment_overrides(self):
        env = _clean_env(SSH_KEY="/tmp/k", VM_IP="10.0.0.2", VM_USER="tester",
                         SSH_PORT="2222")
        with patch.dict(os.environ, env, clear=True):
            argv = ssh_config.ssh_argv()
        assert "/tmp/k" in argv
        assert "tester@10.0.0.2" in argv
        assert argv[argv.index("-p") + 1] == "2222"

    def test_connect_timeout_is_configurable(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            assert "ConnectTimeout=10" in ssh_config.ssh_argv()
            assert "ConnectTimeout=45" in ssh_config.ssh_argv(connect_timeout=45)

    def test_port_is_always_a_string(self):
        """subprocess rejects int argv entries — ssh_port must be stringified."""
        class _Ctx:
            ssh_port = 2222

        with patch.dict(os.environ, _clean_env(), clear=True):
            argv = ssh_config.ssh_argv(_Ctx())
        assert all(isinstance(a, str) for a in argv)
        assert argv[argv.index("-p") + 1] == "2222"

    def test_resolves_without_a_context(self):
        """Suite-local helpers call ssh_argv() with no behave context."""
        with patch.dict(os.environ, _clean_env(VM_IP="10.0.0.3"), clear=True):
            assert "bluefin-test@10.0.0.3" in ssh_config.ssh_argv(None)

    def test_quiet_defaults_off(self):
        """Callers that never asked for LogLevel=ERROR keep byte-identical argv."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            assert "LogLevel=ERROR" not in ssh_config.ssh_argv()

    def test_quiet_adds_log_level_error(self):
        """quiet=True is the single opt-in for suppressing ssh's own diagnostics."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            argv = ssh_config.ssh_argv(quiet=True)
        assert "LogLevel=ERROR" in argv
        assert argv[0] == "ssh"


class TestNoPrivateTransportCopies:
    def test_migrated_modules_do_not_rebuild_ssh_argv(self):
        offenders = [
            rel for rel in MIGRATED_MODULES
            if "StrictHostKeyChecking" in (REPO_ROOT / rel).read_text()
        ]
        assert not offenders, (
            "These modules rebuild the SSH argv inline instead of calling "
            "tests.shared.ssh_config.ssh_argv(): " + ", ".join(offenders)
        )

    def test_migrated_modules_import_the_shared_builder(self):
        missing = [
            rel for rel in MIGRATED_MODULES
            if "ssh_argv" not in (REPO_ROOT / rel).read_text()
        ]
        assert not missing, (
            "These modules no longer use the shared SSH transport builder: "
            + ", ".join(missing)
        )
