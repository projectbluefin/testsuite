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
    context.migration_source_ref = None
    # Run-scoped (set at the root layer so it survives across scenarios):
    # the pre-upgrade VM state that "VM is restored to the pre-upgrade
    # baseline deployment" returns to before each gated upgrade scenario.
    context.lifecycle_baseline = {}
    # Central toggle: set ZSTD_CHUNKED=false to skip @zstd_chunked scenarios
    # when the target image does not yet ship with zstd:chunked compression.
    # Flip to true once projectbluefin/bluefin ships zstd:chunked layers.
    context.zstd_chunked = os.environ.get("ZSTD_CHUNKED", "true").lower() not in (
        "false",
        "0",
        "no",
    )


def before_scenario(context, scenario):
    from tests.shared.quarantine import skip_quarantine

    if skip_quarantine(scenario):
        return
    if "zstd_chunked" in scenario.tags and not context.zstd_chunked:
        scenario.skip(
            "ZSTD_CHUNKED disabled — skip until projectbluefin/bluefin ships zstd:chunked layers"
        )
        return
    context.scenario = scenario
    context.command_stdout = ""
    context.ssh_rc = None
    context.last_ssh_result = None
    context.expected_upgrade_digest = None
    context.original_digest = None
    context.initial_version_id = None
    context.current_version_id = None
    context.migration_source_ref = None
    record_start(context)


def after_scenario(context, scenario):
    record_end(context, scenario)


def _assert_required_lifecycle_passed(features):
    """Reject missing or skipped evidence, including tag-filtered scenarios.

    Required scenarios are those containing the existing mandatory staging
    assertion, not optional capability/migration/idempotency probes. Inspect
    the parsed model rather than after_scenario events: Behave does not call
    scenario hooks for scenarios excluded by a tag filter.
    """
    required = [
        scenario
        for feature in features
        for scenario in feature.walk_scenarios()
        if any(
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
