"""Unit tests for tests/shared/ssh_config.py.

Verifies the single source of truth for SSH connection details: resolution
priority (context attrs > userdata > environment > defaults) and the
populate_ssh_context() contract that suites must call from before_all when
their steps star-import tests.shared.ssh_steps (#712).
"""

import os
import sys
import types
from unittest.mock import MagicMock, patch

import tests.shared.ssh_config as ssh_config


def _bare_context(userdata=None):
    """Context carrying no SSH attributes; attribute reads fall through."""
    ctx = types.SimpleNamespace()
    ctx.config = types.SimpleNamespace(userdata=userdata or {})
    return ctx


def _full_context(userdata=None):
    ctx = _bare_context(userdata)
    ctx.ssh_key = "/ctx/key"
    ctx.vm_ip = "10.1.1.1"
    ctx.ssh_user = "ctxuser"
    ctx.ssh_port = "2200"
    return ctx


_ENV_CLEAR = {
    k: "" for k in (
        "SSH_KEY", "SSH_KEY_PATH", "VM_IP", "VM_USER", "SSH_USER",
        "SSH_PORT", "VM_PORT",
    )
}


class TestResolveSshDetailsDefaults:
    def test_defaults_when_nothing_set(self):
        with patch.dict(os.environ, _ENV_CLEAR, clear=False):
            details = ssh_config.resolve_ssh_details(_bare_context())
        assert details == {
            "ssh_key": ssh_config.DEFAULT_SSH_KEY,
            "vm_ip": ssh_config.DEFAULT_VM_IP,
            "ssh_user": ssh_config.DEFAULT_VM_USER,
            "ssh_port": ssh_config.DEFAULT_SSH_PORT,
        }

    def test_environment_used_when_no_context_or_userdata(self):
        env = dict(_ENV_CLEAR, SSH_KEY="/env/key", VM_IP="192.0.2.10",
                   VM_USER="envuser", SSH_PORT="2222")
        with patch.dict(os.environ, env, clear=False):
            details = ssh_config.resolve_ssh_details(_bare_context())
        assert details["ssh_key"] == "/env/key"
        assert details["vm_ip"] == "192.0.2.10"
        assert details["ssh_user"] == "envuser"
        assert details["ssh_port"] == "2222"

    def test_userdata_beats_environment(self):
        env = dict(_ENV_CLEAR, SSH_KEY="/env/key", VM_IP="192.0.2.10")
        userdata = {"ssh_key": "/ud/key", "vm_ip": "10.9.9.9"}
        with patch.dict(os.environ, env, clear=False):
            details = ssh_config.resolve_ssh_details(_bare_context(userdata))
        assert details["ssh_key"] == "/ud/key"
        assert details["vm_ip"] == "10.9.9.9"

    def test_context_attributes_beat_everything(self):
        env = dict(_ENV_CLEAR, SSH_KEY="/env/key")
        userdata = {"ssh_key": "/ud/key"}
        with patch.dict(os.environ, env, clear=False):
            details = ssh_config.resolve_ssh_details(_full_context(userdata))
        assert details["ssh_key"] == "/ctx/key"
        assert details["vm_ip"] == "10.1.1.1"
        assert details["ssh_user"] == "ctxuser"
        assert details["ssh_port"] == "2200"


class TestPopulateSshContext:
    def test_sets_all_attributes_run_ssh_requires(self):
        ctx = _bare_context()
        with patch.dict(os.environ, _ENV_CLEAR, clear=False):
            ssh_config.populate_ssh_context(ctx)
        # These are exactly the attributes run_ssh() in
        # tests/shared/ssh_steps.py dereferences.
        for attr in ("ssh_key", "vm_ip", "ssh_user", "ssh_port"):
            assert getattr(ctx, attr, None), f"context.{attr} not populated"

    def test_sets_values_from_environment(self):
        ctx = _bare_context()
        env = dict(_ENV_CLEAR, SSH_KEY="/env/key2", VM_IP="192.0.2.20")
        with patch.dict(os.environ, env, clear=False):
            ssh_config.populate_ssh_context(ctx)
        assert ctx.ssh_key == "/env/key2"
        assert ctx.vm_ip == "192.0.2.20"


class TestSoftwareSuiteWiring:
    """Regression tests for #712: the software suite star-imports
    tests.shared.ssh_steps, so its before_all must populate the context
    attributes run_ssh() dereferences, and the steps module must resolve
    connection details from the same source."""

    @staticmethod
    def _import_software_environment():
        """Import the software environment with qecore stubbed out."""
        for name in ("qecore", "qecore.sandbox", "qecore.common_steps"):
            stub = types.ModuleType(name)
            stub.TestSandbox = MagicMock
            sys.modules[name] = stub
        sys.modules.pop("tests.software.features.environment", None)
        import tests.software.features.environment as mod
        return mod

    def test_before_all_populates_ssh_context_attributes(self):
        env_mod = self._import_software_environment()
        ctx = _bare_context()
        with patch.dict(os.environ, _ENV_CLEAR, clear=False):
            env_mod.before_all(ctx)
        for attr in ("ssh_key", "vm_ip", "ssh_user", "ssh_port"):
            assert getattr(ctx, attr, None), (
                f"software before_all did not set context.{attr}; "
                "shared SSH steps will raise AttributeError"
            )

    def test_before_all_values_come_from_environment(self):
        env_mod = self._import_software_environment()
        ctx = _bare_context()
        env = dict(_ENV_CLEAR, VM_IP="192.0.2.30", SSH_KEY="/env/key3")
        with patch.dict(os.environ, env, clear=False):
            env_mod.before_all(ctx)
        assert ctx.vm_ip == "192.0.2.30"
        assert ctx.ssh_key == "/env/key3"

    def test_bazaar_probe_uses_shared_connection_details(self):
        env_mod = self._import_software_environment()
        ctx = _full_context()
        argv = ["ssh", "-i", "/resolved/key", "-p", "2224", "resolved-user@192.0.2.40"]
        result = types.SimpleNamespace(returncode=0)
        with patch.object(env_mod, "ssh_argv", return_value=argv) as build_argv, \
             patch("subprocess.run", return_value=result) as run:
            assert env_mod._has_bazaar(ctx)

        build_argv.assert_called_once_with(ctx, quiet=True)
        command = run.call_args.args[0]
        assert "/resolved/key" in command
        assert "2224" in command
        assert "resolved-user@192.0.2.40" in command

    def test_before_scenario_passes_context_to_bazaar_probe(self):
        env_mod = self._import_software_environment()
        ctx = _bare_context()
        scenario = types.SimpleNamespace(
            effective_tags={"software"},
            tags={"software"},
            feature=types.SimpleNamespace(tags=set()),
            name="Bazaar scenario",
            skip=MagicMock(),
        )
        with patch.object(env_mod, "_has_bazaar", return_value=False) as probe:
            env_mod.before_scenario(ctx, scenario)

        probe.assert_called_once_with(ctx)
        scenario.skip.assert_called_once()

    def test_steps_module_resolves_via_shared_source(self):
        """_flatpak() must use tests.shared.ssh_config, not private env reads."""
        from tests.unit.test_software_steps import _import_software_steps
        import inspect
        steps_mod = _import_software_steps()
        src = inspect.getsource(steps_mod._flatpak)
        assert "ssh_argv" in src
        assert "os.environ" not in src
