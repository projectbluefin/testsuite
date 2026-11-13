"""Step definitions for update failure and rollback guard scenarios."""
import json
import time

from behave import step
from tests.shared.ssh_steps import *  # noqa: F401,F403
from tests.shared.ssh_steps import run_ssh


def _parse_bootc_status(context):
    raw = getattr(context, "command_stdout", "")
    assert raw, "No bootc status output — run 'sudo bootc status --format=json' first"
    try:
        return json.loads(raw).get("status", json.loads(raw))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"bootc status is not valid JSON: {exc}\n{raw}") from exc


def _skip(context, reason: str) -> None:
    scenario = getattr(context, "scenario", None)
    if scenario is not None:
        try:
            scenario.skip(reason)
        except TypeError:
            scenario.skip()


@step("bootc status rollback deployment matches original image digest")
def bootc_rollback_matches_original(context) -> None:
    """Assert .status.rollback digest matches the pre-upgrade original digest."""
    original_digest = getattr(context, "original_digest", None)
    if not original_digest:
        _skip(context, "original_digest not set — run 'Capture booted image digest' first")
        return

    status = _parse_bootc_status(context)
    rollback = status.get("rollback")
    assert rollback is not None, (
        "bootc status has no rollback deployment (.status.rollback is null). "
        "The rollback guard is broken — the previous deployment was not preserved."
    )
    rollback_digest = (
        rollback.get("image", {}).get("imageDigest")
        or rollback.get("imageDigest")
        or ""
    )
    assert rollback_digest == original_digest, (
        f"Rollback deployment digest {rollback_digest!r} != "
        f"original digest {original_digest!r}"
    )


FORCED_ROLLBACK_REBOOT_DEADLINE_S = 300


@step("Force bootc rollback and reboot")
def force_bootc_rollback_and_reboot(context) -> None:
    """Invoke bootc rollback then reboot and wait for SSH to come back up.

    run_ssh returns (stdout, rc); it sets no context.command_returncode, so
    reading that attribute failed every run, even on a successful rollback
    ("bootc rollback failed: Next boot: rollback deployment", run 43506113077).
    """
    stdout, rc = run_ssh(context, "sudo bootc rollback", timeout=60)
    assert rc == 0, f"bootc rollback exited {rc}: {stdout!r}"
    # Trigger reboot (accept disconnect)
    try:
        run_ssh(context, "sudo systemctl reboot", timeout=10)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(5)
    # Wait for SSH to come back. A firmware boot plus finalizing the staged
    # deployment takes longer than a direct-kernel boot, like the 300 s
    # REBOOT_DEADLINE_S in steps.py.
    deadline = time.time() + FORCED_ROLLBACK_REBOOT_DEADLINE_S
    while time.time() < deadline:
        try:
            _, rc = run_ssh(context, "true", timeout=10)
            if rc == 0:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    raise AssertionError("VM did not come back after forced rollback reboot")


# ── @pending greenboot / corrupted-digest stubs ─────────────────────────────
# These steps back scenarios tagged @pending (skipped by the quarantine hook
# before any step runs).  They exist so `behave --dry-run` sees every phrase
# defined; each skips unconditionally if it is ever reached.


@step("Plant a failing greenboot health check")
def plant_failing_greenboot_check(context) -> None:
    """Blocked: needs a greenboot-enabled VM variant — see feature comments."""
    _skip(context, "greenboot is masked in CI QEMU VMs — scenario is @pending")


@step("Wait for greenboot to exhaust retries and roll back")
def wait_greenboot_rollback(context) -> None:
    """Blocked: needs a greenboot-enabled VM variant — see feature comments."""
    _skip(context, "greenboot is masked in CI QEMU VMs — scenario is @pending")


@step("Remove the planted greenboot health check")
def remove_planted_greenboot_check(context) -> None:
    """Blocked: needs a greenboot-enabled VM variant — see feature comments."""
    _skip(context, "greenboot is masked in CI QEMU VMs — scenario is @pending")


@step("Stage a corrupted image digest via registry mirror")
def stage_corrupted_image_digest(context) -> None:
    """Blocked: needs a registry mirror serving a truncated manifest."""
    _skip(context, "no corrupted-digest registry mirror in CI — scenario is @pending")
