@lifecycle @bluefin
Feature: Update failure and rollback guard
  Validates that failed or blocked bootc upgrades do not leave the system in
  an unbootable state, and that the rollback deployment is preserved across
  staged-upgrade failures.

  greenboot integration: `greenboot-healthcheck.service` triggers automatic
  rollback when the post-upgrade health check fails.  greenboot is masked
  in standard CI QEMU VMs (the check requires functional services that the
  minimal VM does not provide), so scenarios that exercise the full
  greenboot path are tagged @pending.  Scenarios that test the non-greenboot
  failure paths (bootc stage + bad-digest + forced rollback) are runnable.

  Runner: plain SSH behave (no qecore — no GUI interaction needed).

  Background:
    * Bluefin VM is booted and reachable over SSH

  # ── Static health-check assertions ────────────────────────────────────────

  @lifecycle @rollback @status
  Scenario: bootc rollback deployment is available after a normal upgrade
    # After a successful upgrade + reboot, .status.rollback must be non-null.
    # This deployment is what bootc rollback uses; its absence means the
    # rollback guard is broken.
    * VM is restored to the pre-upgrade baseline deployment
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * bootc status shows rollback deployment is available
    * bootc status rollback deployment matches original image digest

  @lifecycle @rollback @status
  Scenario: bootc rollback restores the previous deployment after an upgrade
    * VM is restored to the pre-upgrade baseline deployment
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches upgrade target digest
    * Run SSH command: "sudo bootc rollback"
    * SSH command return code is "0"
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches original image digest

  @lifecycle @rollback @update_failure
  Scenario: Staged deployment can be cancelled before reboot
    # `bootc upgrade` stages a deployment; `bootc rollback` before rebooting
    # discards the staged deployment.  This guards the cancel-before-reboot
    # path that power users rely on when they want to abort an update.
    * VM is restored to the pre-upgrade baseline deployment
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Staged deployment is present in bootc status
    * Run SSH command: "sudo bootc rollback"
    * SSH command return code is "0"
    * Run SSH command: "sudo bootc status --format=json"
    * No staged deployment is present in bootc status
    * Active deployment matches original image digest

  @lifecycle @rollback @update_failure
  Scenario: Forcing rollback via bootc rollback after upgrade lands on previous image
    * VM is restored to the pre-upgrade baseline deployment
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches upgrade target digest
    * bootc status shows rollback deployment is available
    * Force bootc rollback and reboot
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches original image digest
    * bootc status shows deployment is not pinned

  # ── greenboot integration — blocked until CI enables greenboot ────────────

  @pending @lifecycle @rollback @greenboot
  Scenario: greenboot health-check failure triggers automatic rollback
    # BLOCKED: greenboot is masked in CI QEMU VMs.  The healthcheck services
    # (greenboot-healthcheck.service, greenboot-status.service) are not
    # enabled in the minimal test VM, so this scenario cannot run automatically.
    # Unblock: add a test VM variant with greenboot enabled and a known-failing
    # health check script in /etc/greenboot/check/required.d/, then drop @pending.
    #
    # Expected flow:
    #   1. Stage a deployment (any valid upgrade).
    #   2. Reboot into staged deployment.
    #   3. greenboot health check fails (deliberately broken health check script).
    #   4. After max-boot-attempts (3), grub2 reverts to previous deployment.
    #   5. bootc status shows the original digest as active, rollback marker cleared.
    * VM is restored to the pre-upgrade baseline deployment
    * Capture booted image digest for rollback verification
    * Plant a failing greenboot health check
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Reboot VM and wait for SSH
    * Wait for greenboot to exhaust retries and roll back
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches original image digest
    * Remove the planted greenboot health check

  @pending @lifecycle @rollback @greenboot @update_failure
  Scenario: Corrupted staged image causes bootc apply to fail and rollback to activate
    # BLOCKED: requires a test VM that can inject an intentionally corrupted
    # image digest into the staged deployment slot.  The corruption must be
    # detectable by bootc at apply time (invalid layer checksums).
    # Unblock: use a registry mirror that can serve a truncated manifest for
    # a pinned digest, trigger bootc upgrade, confirm apply fails, confirm
    # system boots the original deployment.
    * Capture booted image digest for rollback verification
    * Stage a corrupted image digest via registry mirror
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches original image digest
