"""Unit tests for the chairlift suite's behave hooks (tests/chairlift/features/environment.py)."""
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def env(monkeypatch):
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    qecore_stub = types.ModuleType("qecore")
    sandbox_stub = types.ModuleType("qecore.sandbox")
    sandbox_stub.TestSandbox = MagicMock()
    common_stub = types.ModuleType("qecore.common_steps")
    for name, module in (("behave", behave_stub), ("qecore", qecore_stub),
                         ("qecore.sandbox", sandbox_stub), ("qecore.common_steps", common_stub)):
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("tests.chairlift.features.environment", None)
    module = importlib.import_module("tests.chairlift.features.environment")
    monkeypatch.setattr(module, "take_screenshot", MagicMock())
    monkeypatch.setattr(module, "take_fastfetch_screenshot", MagicMock())
    monkeypatch.setattr(module, "record_start", MagicMock())
    monkeypatch.setattr(module, "record_end", MagicMock())
    return module


def _scenario(*tags, status="passed"):
    return SimpleNamespace(name="s", tags=list(tags), effective_tags=list(tags), skip=MagicMock(),
                           feature=SimpleNamespace(tags=["chairlift_suite"]), status=SimpleNamespace(name=status))


def _context(**extra):
    return SimpleNamespace(config=SimpleNamespace(userdata={}), sandbox=MagicMock(), **extra)


def test_before_all_builds_the_sandbox_and_records_a_setup_failure(env, monkeypatch, tmp_path):
    context = SimpleNamespace(config=SimpleNamespace(userdata={"results_dir": str(tmp_path)}))
    env.before_all(context)
    assert context.sandbox.production is False and context.ssh_user
    assert not (tmp_path / "failed_setup.txt").exists()

    monkeypatch.setattr(env, "TestSandbox", MagicMock(side_effect=RuntimeError("no session")))
    env.before_all(context)
    assert "no session" in context.failed_setup
    assert "no session" in (tmp_path / "failed_setup.txt").read_text()


def test_before_scenario_gives_only_gui_scenarios_the_sandbox_hooks(env):
    context = _context()
    env.before_scenario(context, _scenario("chairlift", "brew_install"))
    context.sandbox.before_scenario.assert_not_called()
    assert context.sandbox._scenario_skipped is False
    gui = _scenario("chairlift", "admin_action")
    env.before_scenario(context, gui)
    context.sandbox.before_scenario.assert_called_once_with(context, gui)


def test_before_scenario_skips_parked_scenarios_and_a_failed_setup(env):
    parked = _scenario("chairlift", "pending")
    env.before_scenario(_context(), parked)
    parked.skip.assert_called_once()
    waiting = _scenario("chairlift", "preview_mode")
    waiting.skip = MagicMock(side_effect=[TypeError, None])
    context = _context(failed_setup="boom")
    env.before_scenario(context, waiting)
    assert waiting.skip.call_count == 2
    context.sandbox.before_scenario.assert_not_called()


def test_after_scenario_cleans_up_an_admin_scenario_even_when_a_step_raises(env, monkeypatch, capsys):
    steps = MagicMock(PROCESS="chairlift")
    steps.restore_automatic_updates.side_effect = AssertionError("still masked")
    monkeypatch.setattr(env, "_steps", lambda: steps)
    context = _context()
    scenario = _scenario("chairlift", "admin_action", status="failed")
    env.after_scenario(context, scenario)
    env.take_screenshot.assert_called_once_with("failed")
    steps.dump_tree.assert_called_once_with(context, "admin")
    steps.stop_password_agent.assert_called_once_with(context)
    steps.stop_app_instances.assert_called_once_with("chairlift")
    context.sandbox.after_scenario.assert_called_once_with(context, scenario)
    assert "WARNING: restoring automatic updates failed: AssertionError: still masked" in capsys.readouterr().out


def test_after_scenario_leaves_ssh_only_and_skipped_scenarios_alone(env, monkeypatch):
    steps = MagicMock(PROCESS="chairlift")
    monkeypatch.setattr(env, "_steps", lambda: steps)
    env.after_scenario(_context(), _scenario("chairlift", "brew_install"))
    env.after_scenario(_context(), _scenario("chairlift", "preview_mode", status="skipped"))
    env.after_scenario(_context(failed_setup="boom"), _scenario("chairlift", "preview_mode"))
    assert steps.mock_calls == []
    env.after_scenario(_context(), _scenario("chairlift", "preview_mode"))
    steps.dump_tree.assert_called_once()
    steps.stop_password_agent.assert_not_called()


def test_after_all_prints_the_homebrew_summary_then_takes_the_expected_screenshot(env, monkeypatch):
    steps = MagicMock()
    monkeypatch.setattr(env, "_steps", lambda: steps)
    env.after_all(_context(failed_setup="boom"))
    env.take_fastfetch_screenshot.assert_not_called()
    env.after_all(_context())
    steps.print_brew_summary.assert_called_once()
    env.take_fastfetch_screenshot.assert_called_once_with()


def test_steps_module_resolves_outside_behave(env):
    assert env._steps().PROCESS == "chairlift"
