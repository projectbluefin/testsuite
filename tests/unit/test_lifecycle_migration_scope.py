"""Where the lifecycle homed-migration scenarios run (#1023).

They switch the VM to a third image, so a targeted upgrade-qualification run
skips them (its baseline restore could not recover), and on non-dakota images
they need an explicit MIGRATION_TARGET. An empty MIGRATION_TARGET, which
e2e.yml always exports, falls back to the default instead of `bootc switch ""`.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
DAKOTA = "ghcr.io/projectbluefin/dakota@sha256:" + "a" * 64
UTAH = "ghcr.io/projectbluefin/utah@sha256:" + "b" * 64


def _load_environment():
    ssh_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_stub.run_ssh = MagicMock()
    sys.modules["tests.shared.ssh_steps"] = ssh_stub
    path = REPO_ROOT / "tests/lifecycle/features/environment.py"
    spec = importlib.util.spec_from_file_location("lifecycle_environment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_steps():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub
    ssh_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_stub.run_ssh = MagicMock()
    sys.modules["tests.shared.ssh_steps"] = ssh_stub
    sys.modules.pop("tests.lifecycle.features.steps.steps", None)
    import tests.lifecycle.features.steps.steps as m

    return m


def test_targeted_run_skips_homed_migration():
    env = _load_environment()
    reason = env.homed_migration_skip_reason(
        {"TARGET_IMAGE": UTAH, "IMAGE": DAKOTA, "MIGRATION_TARGET": "ghcr.io/x:next"}
    )
    assert reason and "targeted upgrade qualification" in reason


def test_non_dakota_image_without_target_skips():
    env = _load_environment()
    reason = env.homed_migration_skip_reason({"IMAGE": UTAH, "MIGRATION_TARGET": ""})
    assert reason and "not a dakota image" in reason


def test_untargeted_dakota_run_keeps_homed_migration():
    env = _load_environment()
    assert env.homed_migration_skip_reason({"IMAGE": DAKOTA, "MIGRATION_TARGET": ""}) is None


def test_explicit_migration_target_runs_on_any_image():
    env = _load_environment()
    assert env.homed_migration_skip_reason({"IMAGE": UTAH, "MIGRATION_TARGET": "ghcr.io/x:next"}) is None


def test_default_targets_match():
    assert _load_environment().DEFAULT_MIGRATION_TARGET == _load_steps().DEFAULT_MIGRATION_TARGET


def test_empty_migration_target_falls_back_to_default(monkeypatch):
    steps = _load_steps()
    monkeypatch.setenv("MIGRATION_TARGET", "")
    assert steps._migration_target() == steps.DEFAULT_MIGRATION_TARGET
    monkeypatch.setenv("MIGRATION_TARGET", " ghcr.io/x:next ")
    assert steps._migration_target() == "ghcr.io/x:next"


def test_e2e_points_the_vm_at_the_target_without_staging():
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/e2e.yml").read_text())
    steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]
    names = [s.get("name") for s in steps]
    assert "Pre-stage target image via bootc switch" not in names
    point = next(s for s in steps if s.get("name") == "Point the VM at the target image")
    assert "bootc switch --mutate-in-place" in point["run"]
    assert "unshare -m" in point["run"] and "remount,rw /sysroot" in point["run"]
    assert point["env"]["TARGET_IMAGE"] == "${{ inputs.target-image }}"


def test_pin_scenario_uses_ostree_admin_pin():
    feature = (REPO_ROOT / "tests/lifecycle/features/bootc.feature").read_text()
    assert "bootc pin" not in feature.replace("bootc pin subcommand", "")
    assert '"sudo ostree admin pin 0"' in feature
    assert '"sudo ostree admin pin --unpin 0"' in feature
