"""Unit tests for smoke suite environment setup helpers."""
import importlib
import itertools
import sys
import types
from unittest.mock import MagicMock, patch


def _setup_stubs():
    # Stub behave
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    # Stub dogtail
    dogtail_stub = types.ModuleType("dogtail")
    tree_stub = types.ModuleType("dogtail.tree")
    tree_stub.root = MagicMock()
    sys.modules["dogtail"] = dogtail_stub
    sys.modules["dogtail.tree"] = tree_stub

    # Stub qecore
    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    # Stub steps and steps.app_support
    steps_stub = types.ModuleType("steps")
    steps_steps_stub = types.ModuleType("steps.steps")
    steps_steps_stub._dismiss_welcome_dialog = MagicMock()
    app_support_stub = types.ModuleType("steps.app_support")
    app_support_stub._IN_CONTAINER = False
    app_support_stub._ssh_run = MagicMock()
    sys.modules["steps"] = steps_stub
    sys.modules["steps.steps"] = steps_steps_stub
    sys.modules["steps.app_support"] = app_support_stub


def _run_before_all(in_container: bool):
    """Drive before_all and return every command it issued, as flat strings.

    Commands are normalised to strings so the assertions below describe the
    settings that must be applied, not the argv shape or call order.
    """
    _setup_stubs()
    sys.modules["steps.app_support"]._IN_CONTAINER = in_container
    mock_ssh_run = MagicMock(returncode=0, stdout="(true, 'true')")
    sys.modules["steps.app_support"]._ssh_run = mock_ssh_run

    with patch("time.sleep"), \
         patch("subprocess.run") as mock_run, \
         patch("tests.shared.ssh_config.populate_ssh_context"), \
         patch("builtins.open", MagicMock()):
        mock_run.return_value = MagicMock(returncode=0, stdout="(true, 'true')")

        env = importlib.import_module("tests.smoke.features.environment")
        env.before_all(MagicMock())

    issued = list(mock_run.call_args_list)
    if in_container:
        issued += list(mock_ssh_run.call_args_list)

    out = []
    for call in issued:
        if not call[0]:
            continue
        arg = call[0][0]
        out.append(" ".join(arg) if isinstance(arg, list) else str(arg))
    return out


def test_before_all_suppresses_idle_lock_on_the_vm():
    """Long smoke runs must not hit the lock screen: both settings get applied."""
    commands = _run_before_all(in_container=False)

    assert any("org.gnome.desktop.session" in c and "idle-delay" in c and "0" in c
               for c in commands), commands
    assert any("org.gnome.desktop.screensaver" in c and "lock-enabled" in c and "false" in c
               for c in commands), commands


def test_before_all_suppresses_idle_lock_from_inside_the_runner_container():
    """The container lane reaches the VM session over SSH, so the same two
    settings must still be applied rather than silently skipped."""
    commands = _run_before_all(in_container=True)

    assert any("idle-delay" in c and "0" in c for c in commands), commands
    assert any("lock-enabled" in c and "false" in c for c in commands), commands


def _import_env():
    _setup_stubs()
    return importlib.import_module("tests.smoke.features.environment")


class _Scenario:
    def __init__(self, tags):
        self.name = "s"
        self.tags = tags
        self.effective_tags = tags
        self.skip = MagicMock()


def _ctx(**attrs):
    ctx = types.SimpleNamespace(sandbox=None, failed_setup=None, **attrs)
    return ctx


def test_ci_seeds_flatpaks_mirrors_e2e_preload_condition():
    """Same refs as e2e.yml: contains(inputs.image, '/bluefin'|'/utah'), case-insensitive."""
    env = _import_env()
    seeded = [
        "ghcr.io/projectbluefin/bluefin:latest",
        "ghcr.io/projectbluefin/bluefin-dx@sha256:460d",
        "ghcr.io/projectbluefin/utah@sha256:a0ba",
        "GHCR.IO/ProjectBluefin/Bluefin:stable",
        "ghcr.io/ublue-os/bluefin-nvidia:gts",
    ]
    unseeded = [
        "ghcr.io/ublue-os/bazzite:stable",
        "ghcr.io/projectbluefin/common:latest",
        "ghcr.io/projectbluefin/dakota@sha256:6e8f",
        "ghcr.io/projectbluefin/testsuite:e2e-123",
    ]
    assert all(env.ci_seeds_flatpaks(r) for r in seeded)
    assert not any(env.ci_seeds_flatpaks(r) for r in unseeded)


def test_ci_seeded_flatpak_skips_on_unseeded_bluefin_family_image():
    env = _import_env()
    scenario = _Scenario(["bluefin", "permissions", "ci_seeded_flatpak"])
    env.before_scenario(_ctx(is_bluefin_image=True, ci_seeds_flatpaks=False), scenario)
    scenario.skip.assert_called_once()
    assert "ci_seeded_flatpak" in scenario.skip.call_args[0][0]


def test_ci_seeded_flatpak_runs_on_seeded_image():
    env = _import_env()
    scenario = _Scenario(["bluefin", "permissions", "ci_seeded_flatpak"])
    with patch.object(env, "configure_screenshot_context"), \
         patch.object(env, "record_start"):
        env.before_scenario(_ctx(is_bluefin_image=True, ci_seeds_flatpaks=True), scenario)
    scenario.skip.assert_not_called()


def test_before_all_derives_seed_flag_from_base_image_first():
    """BASE_IMAGE wins over the composed IMAGE, so composed runs keep the seed contract."""
    _setup_stubs()
    sandbox_stub = types.ModuleType("qecore.sandbox")
    sandbox_stub.TestSandbox = MagicMock()
    sys.modules["qecore.sandbox"] = sandbox_stub
    sys.modules["qecore"].__path__ = []
    sys.modules.pop("tests.smoke.features.environment", None)
    env = importlib.import_module("tests.smoke.features.environment")
    ctx = MagicMock()
    ctx.config.userdata = {"image": "ghcr.io/ublue-os/bazzite:stable"}
    with patch.dict("os.environ", {"BASE_IMAGE": "ghcr.io/projectbluefin/utah:latest",
                                   "IMAGE": "ghcr.io/projectbluefin/testsuite:e2e-1"}), \
         patch("time.sleep"), patch("time.time", side_effect=itertools.count(0, 100)), \
         patch("subprocess.run") as run, \
         patch("tests.shared.ssh_config.populate_ssh_context"), \
         patch("builtins.open", MagicMock()):
        run.return_value = MagicMock(returncode=0, stdout="(true, 'true')")
        env.before_all(ctx)
    sys.modules.pop("qecore.sandbox", None)
    sys.modules.pop("tests.smoke.features.environment", None)
    assert ctx.ci_seeds_flatpaks is True
    assert ctx.image_under_test == "ghcr.io/projectbluefin/utah:latest"
