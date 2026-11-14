"""`Skip unless the image ships "<path>"` gates content that reaches images at different times."""
import importlib
import sys
import types
from unittest.mock import MagicMock


def _import_ssh_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub
    sys.modules.pop("tests.shared.ssh_steps", None)
    return importlib.import_module("tests.shared.ssh_steps")


def _context_after(rc):
    m = _import_ssh_steps()
    context = MagicMock()
    commands = []

    def fake_run_ssh(ctx, cmd, timeout=60):
        commands.append(cmd)
        ctx.ssh_rc = rc
        return "", rc

    m.run_ssh = fake_run_ssh
    m.skip_unless_image_ships(context, "/usr/share/flatpak/preinstall.d/compass.preinstall")
    return context, commands


def test_missing_file_skips_with_the_path():
    context, commands = _context_after(1)
    assert commands == ["test -e /usr/share/flatpak/preinstall.d/compass.preinstall"]
    context.scenario.skip.assert_called_once_with(
        "image does not ship /usr/share/flatpak/preinstall.d/compass.preinstall"
    )


def test_present_file_runs_the_scenario():
    context, _ = _context_after(0)
    context.scenario.skip.assert_not_called()
