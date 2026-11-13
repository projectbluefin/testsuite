"""
Lifecycle test environment — plain SSH, no qecore/AT-SPI.

This suite validates bootc upgrade/rollback/switch over SSH.
No GNOME session interaction needed — pure CLI commands.
"""
import os

from tests.shared.ssh_steps import *  # noqa: F401,F403

try:
    from tests.shared.timing import record_end, record_start
except Exception:  # noqa: BLE001
    def record_start(context):
        return None

    def record_end(context, scenario):
        return None


# Same default as steps.py's _migration_target().
DEFAULT_MIGRATION_TARGET = "ghcr.io/projectbluefin/dakota:next"


def homed_migration_skip_reason(environ=None):
    """Why the homed migration scenarios cannot run in this run, or None.

    - A targeted run (TARGET_IMAGE) is release qualification: its upgrade
      scenarios restore a pre-upgrade baseline before each upgrade, and a
      migration ``bootc switch`` to a third image leaves that baseline
      unreachable for the scenarios after it. Migration runs separately.
    - The default target is dakota:next, so on another image family the
      scenarios need an explicit MIGRATION_TARGET (a utah VM must not be
      switched to dakota).
    """
    env = os.environ if environ is None else environ
    if env.get("TARGET_IMAGE", "").strip():
        return (
            "homed migration is not part of targeted upgrade qualification: it "
            "switches the VM to a third image, which the upgrade scenarios' "
            "baseline restore cannot recover. Run it in an untargeted lifecycle "
            "run (e2e.yml extra-tags: homed_migration)."
        )
    if not env.get("MIGRATION_TARGET", "").strip() and "/dakota" not in env.get("IMAGE", ""):
        return (
            "no MIGRATION_TARGET set and this is not a dakota image; the default "
            f"target {DEFAULT_MIGRATION_TARGET} only applies to dakota."
        )
    return None


def before_all(context):
    """Set up SSH connection parameters from environment."""
    context.vm_ip = os.environ.get("VM_IP", "")
    context.ssh_user = os.environ.get("VM_USER", "bluefin-test")
    context.ssh_key = os.environ.get("SSH_KEY", "/etc/ssh/test-key/id_ed25519")
    context.ssh_port = os.environ.get("SSH_PORT", "") or None
    context.expected_upgrade_digest = None
    context.original_digest = None
    context.initial_version_id = None
    context.current_version_id = None
    # Run-scoped (set at the root layer so it survives across scenarios):
    # the pre-upgrade VM state that "VM is restored to the pre-upgrade
    # baseline deployment" returns to before each gated upgrade scenario.
    context.lifecycle_baseline = {}


def before_scenario(context, scenario):
    from tests.shared.quarantine import skip_quarantine

    if skip_quarantine(scenario):
        return
    if "homed_migration" in scenario.effective_tags:
        reason = homed_migration_skip_reason()
        if reason:
            print(f"SKIP Scenario {scenario.name}: {reason}", flush=True)
            scenario.skip(reason)
            return
    context.scenario = scenario
    context.command_stdout = ""
    context.ssh_rc = None
    context.last_ssh_result = None
    context.expected_upgrade_digest = None
    context.original_digest = None
    context.initial_version_id = None
    context.current_version_id = None
    record_start(context)


def after_scenario(context, scenario):
    record_end(context, scenario)


def _assert_required_lifecycle_passed(features):
    """Reject missing or skipped evidence, including tag-filtered scenarios.

    Required scenarios are those containing the existing mandatory staging
    assertion, not optional capability/migration/idempotency probes. Inspect
    the parsed model rather than after_scenario events: Behave does not call
    scenario hooks for scenarios excluded by a tag filter. Scenarios parked
    by a skip tag (@pending, @future, @quarantine, @hardware_blocked) never
    run, so they are not required.
    """
    from tests.shared.quarantine import is_non_runnable

    required = [
        scenario
        for feature in features
        for scenario in feature.walk_scenarios()
        if not is_non_runnable(scenario)
        and any(
            step.name == "bootc upgrade output indicates image was staged"
            for step in scenario.steps
        )
    ]
    assert required, "Lifecycle qualification has no required upgrade scenarios"
    incomplete = [
        scenario.name for scenario in required
        if scenario.status.name != "passed"
        or any(step.status.name != "passed" for step in scenario.steps)
    ]
    assert not incomplete, (
        "Lifecycle qualification requires every upgrade/rollback assertion to "
        "pass; skipped or incomplete required scenarios: " + "; ".join(incomplete)
    )


def after_all(context):
    # TARGET_IMAGE is the existing targeted-upgrade input, exported by e2e.yml.
    # Untargeted exploratory/manual runs retain their capability-skip semantics.
    if os.environ.get("TARGET_IMAGE", "").strip():
        # The runner owns the complete parsed model, including filtered features
        # whose before_feature/after_feature hooks never ran.
        _assert_required_lifecycle_passed(context._runner.features)
