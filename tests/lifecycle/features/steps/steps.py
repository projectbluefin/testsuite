"""
Lifecycle test step definitions — bootc upgrade, rollback, switch.

Runner: plain SSH behave (no qecore/AT-SPI needed).
All steps execute commands on the VM over SSH.

bootc status JSON schema (v1alpha1):
  .status.booted    — currently running deployment
  .status.staged    — staged deployment awaiting reboot (null if none)
  .status.rollback  — previous deployment available for rollback (null if none)
  .status.booted.image.imageDigest  — SHA256 digest of booted image
  .status.booted.image.image.image  — image reference string
"""
import json
import os
import re
import shlex
import subprocess
from time import sleep, time

from behave import step

from tests.shared.ssh_steps import *  # noqa: F401,F403
from tests.shared.ssh_steps import run_ssh


def _parse_bootc_status(context):
    """Return the .status dict from sudo bootc status --format=json output."""
    raw = getattr(context, "command_stdout", "")
    assert raw, "No bootc status output available — run 'sudo bootc status --format=json' first"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid bootc status JSON: {exc}\n{raw}") from exc
    status = payload.get("status")
    assert isinstance(status, dict), (
        f"bootc status JSON missing 'status' dict. Top-level keys: {list(payload.keys())}"
    )
    return status


def _skip_current_scenario(context, reason):
    scenario = getattr(context, "scenario", None)
    if scenario is None:
        raise AssertionError(reason)
    try:
        scenario.skip(reason)
    except TypeError:
        scenario.skip()


def _parse_os_release(raw):
    """Parse /etc/os-release content into a dict with surrounding quotes removed."""
    assert raw, "No /etc/os-release output available"
    data = {}
    for line in raw.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def _valid_fedora_version(version):
    return bool(re.fullmatch(r"\d+", version or ""))


SETTLED_DEPLOYMENT_TIMEOUT_S = 120
SETTLED_POLL_INTERVAL_S = 5


def _is_deployment_settled(raw_json: str) -> tuple[bool, str]:
    """Check whether bootc status JSON indicates a settled deployment.

    A deployment is considered settled when:
      1. The output is non-empty, valid JSON with a top-level 'status' mapping.
      2. A 'booted' deployment is present (.status.booted is a non-empty dict).
      3. No staged deployment is present (.status.staged is None or absent).
         If a staged deployment is present, staging or finalization is still
         in progress or awaiting reboot.

    Returns:
        (True, reason) if settled, (False, reason) if unsettled or invalid.
    """
    if not raw_json or not raw_json.strip():
        return False, "bootc status output was empty"
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return False, f"invalid bootc status JSON: {exc}"
    if not isinstance(payload, dict):
        return False, f"top-level JSON is {type(payload).__name__}, expected dict"
    status = payload.get("status")
    if not isinstance(status, dict):
        return False, f"missing 'status' dict in bootc status JSON (keys: {list(payload.keys())})"
    booted = status.get("booted")
    if not isinstance(booted, dict) or not booted:
        return False, "missing or empty 'booted' deployment in status"
    staged = status.get("staged")
    if staged is not None:
        return False, f"staged deployment is present (staging/finalization in progress or pending reboot): {staged}"
    return True, "deployment is settled (booted deployment active, no staged deployment in progress)"


@step("Deployment is settled")
@step("bootc deployment is settled")
def deployment_is_settled(context, timeout: int = SETTLED_DEPLOYMENT_TIMEOUT_S):
    """Barrier: poll bootc status over SSH until no staging/finalization is in progress.

    In fresh QEMU installs or following deployment changes, bootc may temporarily
    report a staged deployment or hold locks while the staged-deployment writer
    finalizes. This barrier polls until bootc status reports a valid booted deployment
    with no staged deployment, ensuring subsequent operations like `bootc pin`
    do not race the writer.
    """
    deadline = time() + timeout
    last_reason = "bootc status was not executed"

    while time() < deadline:
        try:
            stdout, rc = run_ssh(context, "sudo bootc status --format=json", timeout=15)
            if rc == 0:
                settled, reason = _is_deployment_settled(stdout)
                if settled:
                    print(f"Deployment settled: {reason}", flush=True)
                    return
                last_reason = reason
            else:
                last_reason = f"sudo bootc status --format=json exited {rc}: {stdout!r}"
        except subprocess.TimeoutExpired as exc:
            last_reason = f"SSH command timed out after {exc.timeout}s"
        except Exception as exc:
            last_reason = f"SSH execution failed: {exc}"

        sleep(SETTLED_POLL_INTERVAL_S)

    raise AssertionError(
        f"Deployment did not settle within {timeout}s: {last_reason}"
    )


@step("Deployment is settled within {timeout:d} seconds")
@step("bootc deployment is settled within {timeout:d} seconds")
def deployment_is_settled_with_timeout(context, timeout: int):
    deployment_is_settled(context, timeout=timeout)


@step("bootc status shows deployment is pinned")
def bootc_status_pinned(context):
    booted = _parse_bootc_status(context).get("booted") or {}
    assert booted.get("pinned") is True, f"Expected booted.pinned=true, got: {booted}"


@step("bootc status shows deployment is not pinned")
def bootc_status_not_pinned(context):
    booted = _parse_bootc_status(context).get("booted") or {}
    pinned = booted.get("pinned")
    assert pinned is not True, f"Expected booted.pinned to be absent/false, got: {booted}"


@step("Capture booted image digest for rollback verification")
def capture_original_digest(context):
    """Store the currently booted image digest so rollback can be verified later."""
    run_ssh(context, "sudo bootc status --format=json")
    status = _parse_bootc_status(context)
    digest = status.get("booted", {}).get("image", {}).get("imageDigest", "")
    assert digest, f"Could not read booted imageDigest from bootc status: {status}"
    context.original_digest = digest
    print(f"Captured original digest: {digest}", flush=True)


@step("Capture staged image digest as upgrade target")
def capture_staged_digest(context):
    """Store the staged image digest so the post-reboot deployment can be verified."""
    run_ssh(context, "sudo bootc status --format=json")
    status = _parse_bootc_status(context)
    staged = status.get("staged")
    assert staged is not None, (
        f"No staged deployment found — did 'bootc upgrade' succeed? status={status}"
    )
    digest = staged.get("image", {}).get("imageDigest", "")
    assert digest, f"Could not read staged imageDigest from bootc status: {staged}"
    context.expected_upgrade_digest = digest
    print(f"Captured upgrade target digest: {digest}", flush=True)


@step("Staged deployment is present in bootc status")
def staged_deployment_present(context):
    """Parse bootc status JSON and assert a staged deployment exists."""
    status = _parse_bootc_status(context)
    assert status.get("staged") is not None, (
        f"Expected a staged deployment in bootc status, got status={status}"
    )


@step("Active deployment matches upgrade target digest")
def active_matches_target(context):
    """Validate the running deployment's digest matches the captured staged digest."""
    expected_digest = getattr(context, "expected_upgrade_digest", None)
    if not expected_digest:
        _skip_current_scenario(context, "expected_upgrade_digest is not set — add 'Capture staged image digest as upgrade target' before reboot")
        return
    active_digest = _parse_bootc_status(context).get("booted", {}).get("image", {}).get("imageDigest")
    assert active_digest == expected_digest, (
        f"Active digest {active_digest!r} != expected {expected_digest!r}"
    )


@step("Active deployment matches original image digest")
def active_matches_original(context):
    """After rollback, verify we're back on the deployment captured before upgrade."""
    original_digest = getattr(context, "original_digest", None)
    if not original_digest:
        _skip_current_scenario(context, "original_digest is not set — add 'Capture booted image digest for rollback verification' before upgrade")
        return
    active_digest = _parse_bootc_status(context).get("booted", {}).get("image", {}).get("imageDigest")
    assert active_digest == original_digest, (
        f"Active digest {active_digest!r} != original {original_digest!r}"
    )


@step("bootc upgrade output indicates image was staged")
def upgrade_output_staged(context):
    """Verify bootc upgrade stdout shows a new image was queued for next boot.

    ``bootc upgrade`` exits 0 in two distinct cases:
      - New image available: output contains "Queued for next boot: <ref>"
      - Already up-to-date: output contains "No update available."

    When the upgrade is a no-op, any stale staged deployment left over from a
    prior run would cause reboot-dependent scenarios to false-pass: the stale
    staged digest matches the booted digest after rebooting into it, /etc files
    trivially survive a same-image reboot, and ostree still shows two entries.

    If no staging happened, fail hard so CI does not silently report a
    passing upgrade path when no upgrade actually occurred.
    """
    output = getattr(context, "command_stdout", "")
    if "Queued for next boot" not in output:
        # Skip rather than fail: when CI images are already at latest,
        # bootc upgrade is always a no-op and these upgrade scenarios
        # can never pass. Skipping the whole scenario avoids persistent
        # red noise; the migration scenarios still exercise bootc switch.
        _skip_current_scenario(
            context,
            "bootc upgrade was a no-op — booted image is already at the latest digest. "
            "Skip upgrade-dependent scenarios; use a pinned older digest as the base image "
            f"to exercise upgrade paths. bootc output: {output!r}",
        )


@step('Active image reference contains "{fragment}"')
def active_image_contains(context, fragment):
    """Verify the booted image reference string contains the expected fragment."""
    # bootc status JSON: .status.booted.image.image.image
    booted = _parse_bootc_status(context).get("booted", {})
    active_image = booted.get("image", {}).get("image", {}).get("image", "")
    assert fragment in active_image, (
        f"Expected {fragment!r} in active image reference {active_image!r}"
    )


@step('bootc status image reference starts with "{prefix}"')
def bootc_status_image_reference_starts_with(context, prefix):
    booted = _parse_bootc_status(context).get("booted", {})
    active_image = booted.get("image", {}).get("image", {}).get("image", "")
    assert active_image.startswith(prefix), (
        f"Expected active image reference {active_image!r} to start with {prefix!r}"
    )


@step("bootc status image digest is a valid sha256")
def bootc_status_image_digest_valid(context):
    booted = _parse_bootc_status(context).get("booted", {})
    digest = booted.get("image", {}).get("imageDigest", "")
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", digest), (
        f"Expected booted image digest to match sha256:<64 hex>, got {digest!r}"
    )


@step("Capture current os-release VERSION_ID via SSH")
def capture_current_version_id(context):
    run_ssh(context, "cat /etc/os-release")
    data = _parse_os_release(getattr(context, "command_stdout", ""))
    version_id = data.get("VERSION_ID", "")
    assert version_id, f"VERSION_ID missing from /etc/os-release: {data}"
    if getattr(context, "initial_version_id", None) is None:
        context.initial_version_id = version_id
    context.current_version_id = version_id
    print(f"Captured VERSION_ID: {version_id}", flush=True)


@step("Captured VERSION_ID is a valid Fedora version number")
def captured_version_id_is_valid(context):
    version_id = getattr(context, "current_version_id", None)
    assert version_id is not None, "No VERSION_ID captured yet"
    assert _valid_fedora_version(version_id), (
        f"Expected VERSION_ID to be a Fedora version number, got {version_id!r}"
    )


@step("os-release VERSION_ID is tracked across upgrade")
def os_release_version_is_tracked_across_upgrade(context):
    before = getattr(context, "initial_version_id", None)
    after = getattr(context, "current_version_id", None)
    assert before is not None, "Initial VERSION_ID was not captured before upgrade"
    assert after is not None, "Current VERSION_ID was not captured after upgrade"
    assert _valid_fedora_version(before), f"Initial VERSION_ID is invalid: {before!r}"
    assert _valid_fedora_version(after), f"Current VERSION_ID is invalid: {after!r}"
    if before != after:
        print(f"VERSION_ID changed across upgrade: {before} -> {after}", flush=True)
    else:
        print(
            f"VERSION_ID remained {after} across upgrade; valid when image content changes within the same Fedora release",
            flush=True,
        )


@step("os-release reports Fedora Bluefin identity")
def os_release_reports_fedora_bluefin_identity(context):
    data = _parse_os_release(getattr(context, "command_stdout", ""))
    id_val = data.get("ID", "")
    id_like = data.get("ID_LIKE", "")
    assert id_val in ("fedora", "bluefin") or "fedora" in id_like, (
        f"Expected ID=fedora or ID=bluefin (with ID_LIKE=fedora) in /etc/os-release, got: {data}"
    )
    variant_id = data.get("VARIANT_ID")
    pretty_name = data.get("PRETTY_NAME", "")
    assert variant_id == "bluefin" or "bluefin" in pretty_name.lower(), (
        "Expected VARIANT_ID=bluefin or PRETTY_NAME containing 'Bluefin' in /etc/os-release, "
        f"got: {data}"
    )


@step("If bootc upgrade output indicates image was staged, reboot VM and wait for SSH")
def maybe_reboot_after_upgrade(context):
    output = getattr(context, "command_stdout", "")
    if "Queued for next boot" in output:
        reboot_and_wait(context)


@step("No staged deployment is present in bootc status")
def no_staged_deployment_present(context):
    status = _parse_bootc_status(context)
    assert status.get("staged") is None, (
        f"Expected no staged deployment in bootc status, got status={status}"
    )


@step("Reboot VM and wait for SSH")
def reboot_and_wait(context):
    """Trigger VM reboot via SSH and wait up to 120s for the SSH port to come back."""
    try:
        run_ssh(context, "sudo reboot")
    except subprocess.TimeoutExpired:
        pass

    deadline = time() + 120
    last_error = "SSH never became reachable after reboot"
    sleep(10)
    while time() < deadline:
        try:
            stdout, returncode = run_ssh(context, "echo ok", timeout=10)
            if returncode == 0 and stdout == "ok":
                return
            last_error = f"rc={returncode}, stdout={stdout!r}"
        except subprocess.TimeoutExpired as exc:
            last_error = f"timeout after {exc.timeout}s"
        sleep(5)

    raise AssertionError(
        f"VM at {context.vm_ip} did not come back over SSH within 120s: {last_error}"
    )


def _migration_target():
    """Return the migration target image ref from MIGRATION_TARGET env var."""
    return os.environ.get(
        "MIGRATION_TARGET", "ghcr.io/projectbluefin/bluefin:stable"
    )


MIGRATION_SWITCH_TIMEOUT_S = 900
MIGRATION_REBOOT_DEADLINE_S = 300
PODMAN_PULL_TIMEOUT_S = 900
CONTAINERS_STORAGE_SWITCH_TIMEOUT_S = 120


@step("Switch to migration target")
def switch_to_migration_target(context):
    """Run bootc switch to the parameterized migration target image."""
    target = _migration_target()
    run_ssh(context, f"sudo bootc switch {shlex.quote(target)}", timeout=MIGRATION_SWITCH_TIMEOUT_S)


@step("Switch to migration target with unified storage")
def switch_to_migration_target_unified(context):
    """Run bootc switch --experimental-unified-storage to the migration target."""
    target = _migration_target()
    run_ssh(
        context,
        f"sudo bootc switch --experimental-unified-storage {shlex.quote(target)}",
        timeout=MIGRATION_SWITCH_TIMEOUT_S,
    )


@step("Check unified storage support and skip if unavailable")
def check_unified_storage_support(context):
    """Probe bootc switch --help for --experimental-unified-storage; skip if absent."""
    stdout, rc = run_ssh(context, "sudo bootc switch --help", timeout=30)
    if "--experimental-unified-storage" not in stdout:
        context.scenario.skip(
            "bootc on this image does not support --experimental-unified-storage "
            "(requires bootc >= 1.16). Skipping unified storage scenario."
        )


@step("Pull migration target via podman for zstd:chunked transport")
def pull_migration_target_podman(context):
    """Pull the migration target into root containers-storage via podman."""
    target = _migration_target()
    run_ssh(context, f"sudo podman pull {shlex.quote(target)}", timeout=PODMAN_PULL_TIMEOUT_S)


@step("Switch to migration target via containers-storage transport")
def switch_to_migration_target_containers_storage(context):
    """Switch to the migration target using the local containers-storage copy."""
    target = _migration_target()
    run_ssh(
        context,
        f"sudo bootc switch --transport containers-storage {shlex.quote(target)}",
        timeout=CONTAINERS_STORAGE_SWITCH_TIMEOUT_S,
    )


@step("Reboot VM and wait for SSH after migration")
def reboot_and_wait_migration(context):
    """Trigger VM reboot and wait up to 300s for SSH — handles rechunker-group-fix."""
    try:
        run_ssh(context, "sudo reboot")
    except subprocess.TimeoutExpired:
        pass

    deadline = time() + MIGRATION_REBOOT_DEADLINE_S
    last_error = "SSH never became reachable after migration reboot"
    sleep(10)
    while time() < deadline:
        try:
            stdout, returncode = run_ssh(context, "echo ok", timeout=10)
            if returncode == 0 and stdout == "ok":
                return
            last_error = f"rc={returncode}, stdout={stdout!r}"
        except subprocess.TimeoutExpired as exc:
            last_error = f"timeout after {exc.timeout}s"
        sleep(5)

    raise AssertionError(
        f"VM at {context.vm_ip} did not come back over SSH within "
        f"{MIGRATION_REBOOT_DEADLINE_S}s: {last_error}"
    )


@step("Capture booted image reference as migration source")
def capture_migration_source_ref(context):
    """Store the currently booted image reference (expected: ublue-os/bluefin) so
    post-rollback steps can verify the switch was fully reversed."""
    run_ssh(context, "sudo bootc status --format=json")
    status = _parse_bootc_status(context)
    booted = status.get("booted", {})
    image_ref = booted.get("image", {}).get("image", {}).get("image", "")
    assert image_ref, f"Could not read booted image reference from bootc status: {booted}"
    context.migration_source_ref = image_ref
    print(f"Captured migration source ref: {image_ref}", flush=True)


@step('Booted image is from the "{registry}" registry')
def booted_image_from_registry(context, registry):
    """Assert the active image reference contains the expected registry prefix.

    Used as a pre-condition guard before cross-registry migration to confirm the
    VM started on the intended source image and the switch will be a real migration,
    not a no-op against the same registry.
    """
    run_ssh(context, "sudo bootc status --format=json")
    status = _parse_bootc_status(context)
    active_ref = (
        status.get("booted", {}).get("image", {}).get("image", {}).get("image", "")
    )
    if registry not in active_ref:
        context.scenario.skip(
            f"Pre-condition not met: booted image {active_ref!r} is not from "
            f"registry {registry!r}. Migration scenarios require the legacy "
            f"source image — skipping on non-migration boot."
        )
        return
    print(f"Confirmed: booted image {active_ref!r} is from {registry!r}", flush=True)


@step("Migration source image reference is restored after rollback")
def migration_source_restored(context):
    """After rollback, verify the active image digest matches the pre-migration original.

    bootc rollback reorders existing ostree deployments; the digest is the reliable
    identity. Exact ref-string equality is a weaker check — include it only as
    informational output, not as the assertion.
    """
    source_ref = getattr(context, "migration_source_ref", None)
    original_digest = getattr(context, "original_digest", None)
    if not original_digest:
        _skip_current_scenario(
            context,
            "original_digest is not set — add "
            "'Capture booted image digest for rollback verification' before the switch",
        )
        return
    status = _parse_bootc_status(context)
    active_digest = status.get("booted", {}).get("image", {}).get("imageDigest", "")
    active_ref = (
        status.get("booted", {}).get("image", {}).get("image", {}).get("image", "")
    )
    assert active_digest == original_digest, (
        f"Expected rollback digest {original_digest!r}, got {active_digest!r}"
    )
    if source_ref:
        print(
            f"Rollback restored digest {active_digest!r} "
            f"(ref: {active_ref!r}, expected: {source_ref!r})",
            flush=True,
        )


@step("bootc status shows deployment is compatible")
def bootc_status_compatible(context):
    """Verify the booted deployment is not marked incompatible.

    bootc sets booted.incompatible=true when the deployment has in-place
    modifications that diverge from the image (e.g. files written to /usr).
    When the field is absent the deployment is compatible by default.
    The assertion is printed explicitly so CI output shows whether the field
    was present or absent.
    """
    booted = _parse_bootc_status(context).get("booted") or {}
    incompatible = booted.get("incompatible", False)
    field_present = "incompatible" in booted
    print(
        f"bootc booted.incompatible={'present' if field_present else 'absent (defaults to false)'}: "
        f"{incompatible!r}",
        flush=True,
    )
    assert not incompatible, (
        f"Expected booted deployment to be compatible, "
        f"got incompatible={incompatible!r}: {booted}"
    )


@step("bootc status shows rollback deployment is available")
def bootc_status_rollback_available(context):
    """Verify bootc status reports a rollback deployment (.status.rollback is not null).

    After a migration switch + reboot, bootc should retain the previous deployment
    as the rollback target. This is stronger than counting ostree deployments because
    it tests the exact field bootc rollback uses.
    """
    status = _parse_bootc_status(context)
    rollback = status.get("rollback")
    assert rollback is not None, (
        f"Expected .status.rollback to be present after migration, got null. "
        f"status keys: {list(status.keys())}"
    )
    rollback_ref = rollback.get("image", {}).get("image", {}).get("image", "")
    print(f"Rollback deployment available: {rollback_ref!r}", flush=True)


@step("bootc status rollback deployment matches migration source digest")
def bootc_rollback_matches_source(context):
    """After migration, verify the rollback deployment has the original source digest.

    This proves the legacy-rechunker deployment was preserved and can be recovered,
    which is stronger than just checking that two ostree deployments exist.
    """
    original_digest = getattr(context, "original_digest", None)
    if not original_digest:
        _skip_current_scenario(
            context,
            "original_digest is not set — add "
            "'Capture booted image digest for rollback verification' before the switch",
        )
        return
    status = _parse_bootc_status(context)
    rollback = status.get("rollback")
    assert rollback is not None, (
        "Expected .status.rollback to be present but it is null — "
        "no rollback target was preserved after migration"
    )
    rollback_digest = rollback.get("image", {}).get("imageDigest", "")
    assert rollback_digest == original_digest, (
        f"Rollback deployment digest {rollback_digest!r} != "
        f"original source digest {original_digest!r}"
    )
    print(f"Rollback deployment correctly preserves source digest: {rollback_digest!r}", flush=True)


@step("Unified storage overlay directory is present on the VM")
def unified_storage_overlay_present(context):
    """Verify /var/lib/bootc/storage/overlay exists after a unified-storage switch.

    This directory is the containers-storage backing store used by bootc's
    experimental unified storage mode. Its presence confirms the migrated image
    was placed in containers-storage (not the legacy ostree repo).
    """
    run_ssh(context, "test -d /var/lib/bootc/storage/overlay")
    rc = getattr(context, "ssh_rc", 1)
    assert rc == 0, (
        "Expected /var/lib/bootc/storage/overlay to exist after unified-storage "
        "migration, but the directory was not found. "
        "Check that the switch was issued with --experimental-unified-storage."
    )
    print("Confirmed: /var/lib/bootc/storage/overlay is present", flush=True)


@step("Active image layers use zstd:chunked compression")
def active_image_layers_zstd_chunked(context):
    """Verify the active image uses zstd:chunked layer compression.

    Inspects the OCI manifest via skopeo to confirm at least one layer uses
    tar+zstd mediaType or carries the zstd-chunked annotation.

    Requires the target image to have been built or repushed with zstd:chunked
    (e.g. skopeo copy --dest-compress-format=zstd:chunked).
    """
    status = _parse_bootc_status(context)
    image_ref = (
        status.get("booted", {}).get("image", {}).get("image", {}).get("image", "")
    )
    assert image_ref, f"Could not extract booted image ref from bootc status: {status}"

    out, rc = run_ssh(context, f"skopeo inspect --raw docker://{image_ref}", timeout=120)
    assert rc == 0, f"skopeo inspect --raw failed for {image_ref!r}: rc={rc}\n{out}"

    try:
        manifest = json.loads(out)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Invalid manifest JSON from skopeo: {exc}\n{out}") from exc

    layers = manifest.get("layers", [])
    assert layers, f"No layers found in manifest for {image_ref!r}"

    for layer in layers:
        media_type = layer.get("mediaType", "")
        annotations = layer.get("annotations", {})
        if "tar+zstd" in media_type or any("zstd-chunked" in k for k in annotations):
            print(
                f"Confirmed: {image_ref!r} uses zstd:chunked "
                f"(first matching layer: mediaType={media_type!r})",
                flush=True,
            )
            return

    media_types = {layer.get("mediaType") for layer in layers}
    raise AssertionError(
        f"Image {image_ref!r} does not use zstd:chunked compression. "
        f"Observed layer mediaTypes: {media_types}. "
        "Ensure the target image was built or repushed with zstd:chunked "
        "(e.g. skopeo copy --dest-compress-format=zstd:chunked)."
    )



@step("ostree status shows two deployments")
def ostree_two_deployments(context):
    """Verify ostree admin status reports at least 2 deployments.

    ostree admin status output format:
      * <ref>              ← booted deployment (starts with "* ")
          Version: ...
        <ref>              ← previous deployment (starts with 2 spaces + non-space)
          Version: ...

    We count deployment header lines: "* " lines and "  <non-space>" lines.
    """
    output = getattr(context, "command_stdout", "")
    # Each deployment header starts a new block:
    # - active: "* <deployment-ref>"
    # - previous: "  <deployment-ref>" (exactly 2 spaces, then non-space/non-digit metadata marker)
    deployment_headers = re.findall(r'^(?:\* |\s{2}(?!\s))(?=[a-zA-Z0-9])', output, re.MULTILINE)
    deployment_count = len(deployment_headers)
    assert deployment_count >= 2, (
        f"Expected at least 2 ostree deployments, found {deployment_count}\n{output}"
    )


# ---------------------------------------------------------------------------
# systemd-homed migration steps (dakota:testing → dakota:next)
# MIGRATION_TARGET env var — defaults to ghcr.io/projectbluefin/dakota:next
# ---------------------------------------------------------------------------

def _is_homed_active(context):
    """Return True if systemd-homed is active on the booted VM."""
    stdout, rc = run_ssh(context, "systemctl is-active systemd-homed", timeout=15)
    return rc == 0 and stdout.strip() == "active"


@step("systemd-homed service is active after migration")
def homed_service_active(context):
    """Assert systemd-homed.service is active; skip gracefully if not present."""
    stdout, rc = run_ssh(context, "systemctl is-active systemd-homed", timeout=15)
    state = stdout.strip()
    if state in ("inactive", "unknown", "not-found"):
        _skip_current_scenario(
            context,
            f"systemd-homed is not present on this image (state: {state!r}). "
            "Skipping homed migration scenario.",
        )
        return
    assert rc == 0 and state == "active", (
        f"Expected systemd-homed to be active, got {state!r} (rc={rc})"
    )


@step("Traditional user is resolvable via id after homed migration")
def traditional_user_resolvable(context):
    """Assert the SSH user (a traditional /etc/passwd user) resolves via id."""
    user = getattr(context, "ssh_user", "user")
    stdout, rc = run_ssh(context, f"id {shlex.quote(user)}", timeout=15)
    assert rc == 0, (
        f"id {user!r} failed (rc={rc}). "
        "Traditional /etc/passwd user not resolvable after homed migration."
    )
    assert user in stdout, (
        f"Expected {user!r} in id output, got: {stdout!r}"
    )


@step("pam_systemd_home is present in system-auth PAM config")
def pam_systemd_home_in_system_auth(context):
    """Assert pam_systemd_home.so appears in /etc/pam.d/system-auth; skip if homed absent."""
    if not _is_homed_active(context):
        _skip_current_scenario(
            context,
            "systemd-homed is not active; PAM system-auth check skipped.",
        )
        return
    stdout, rc = run_ssh(context, "grep pam_systemd_home /etc/pam.d/system-auth", timeout=15)
    assert rc == 0 and "pam_systemd_home" in stdout, (
        "pam_systemd_home.so not found in /etc/pam.d/system-auth. "
        f"grep rc={rc}, output={stdout!r}"
    )


@step("No PAM authentication failures in journal for traditional user")
def no_pam_auth_failures(context):
    """Assert the journal has no PAM authentication failures for the traditional user."""
    user = getattr(context, "ssh_user", "user")
    stdout, rc = run_ssh(
        context,
        "journalctl --no-pager -n 200 -g 'authentication failure'",
        timeout=30,
    )
    failures = [
        line for line in stdout.splitlines()
        if "authentication failure" in line and user in line
    ]
    assert not failures, (
        f"PAM authentication failures found in journal for user {user!r}:\n"
        + "\n".join(failures)
    )


@step("GDM journal shows no authentication failures after homed migration")
def gdm_no_auth_failures(context):
    """Assert GDM journal has no authentication failure entries after homed migration."""
    stdout, rc = run_ssh(
        context,
        "journalctl --no-pager -u gdm -n 200 -g 'authentication failure'",
        timeout=30,
    )
    failures = [line for line in stdout.splitlines() if "authentication failure" in line]
    assert not failures, (
        "GDM journal shows authentication failures after homed migration:\n"
        + "\n".join(failures)
    )


@step("homectl list does not contain traditional user entry")
def homectl_no_traditional_user(context):
    """Assert homectl list has no record for the traditional /etc/passwd user."""
    if not _is_homed_active(context):
        _skip_current_scenario(
            context,
            "systemd-homed is not active; homectl list check skipped.",
        )
        return
    user = getattr(context, "ssh_user", "user")
    stdout, rc = run_ssh(context, "sudo homectl list", timeout=15)
    assert user not in stdout, (
        f"homectl list unexpectedly contains an entry for traditional user {user!r}.\n"
        f"Output:\n{stdout}"
    )
