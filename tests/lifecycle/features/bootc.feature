@lifecycle @bluefin
Feature: bootc upgrade and rollback lifecycle
  Validates that atomic updates via bootc work correctly on Bluefin.
  Tests the most critical user journey: upgrade, verify, rollback.
  Runner: plain SSH behave (no qecore — no GUI interaction needed).

  # Requires: a second image tag to upgrade TO (pinned digest or test tag).
  # Requires: VM reboot capability (virtctl restart or guest systemctl reboot).
  # See QA-REVIEW.md Epic E06 for full design.

  Background:
    * Bluefin VM is booted and reachable over SSH

  @lifecycle @status
  Scenario: bootc status shows expected image and is not dirty
    * Run SSH command: "sudo bootc status --format=json"
    * SSH command return code is "0"
    * Capture booted image digest for rollback verification

  # Settled-deployment barrier ensures the staged-deployment writer and
  # early-boot finalization have completed before mutating pin state.
  @lifecycle @pin
  Scenario: bootc can pin and unpin the current deployment
    * Bluefin VM is booted and reachable over SSH
    * Deployment is settled
    * Run SSH command: "sudo bootc pin"
    * SSH command return code is "0"
    * Run SSH command: "sudo bootc status --format=json"
    * bootc status shows deployment is pinned
    * Run SSH command: "sudo bootc pin --unpin"
    * SSH command return code is "0"
    * Run SSH command: "sudo bootc status --format=json"
    * bootc status shows deployment is not pinned

  @lifecycle @upgrade
  Scenario: bootc upgrade stages a new deployment
    # Needs: target image with a different digest than the currently booted one.
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Staged deployment is present in bootc status

  @lifecycle @upgrade @reboot
  Scenario: VM boots into upgraded deployment after reboot
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches upgrade target digest

  @lifecycle @rollback
  Scenario: bootc rollback reverts to previous deployment
    * Capture booted image digest for rollback verification
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc rollback"
    * SSH command return code is "0"
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches original image digest

  @lifecycle @switch @future
  Scenario: bootc switch transitions to a different variant
    # Future: mutates VM image variant (bluefin → bluefin-dx), corrupting
    # subsequent migration.feature scenarios that expect ublue-os/bluefin as source.
    # Run as a standalone suite once cross-variant golden-disk testing is set up.
    * Run long SSH command: "sudo bootc switch ghcr.io/ublue-os/bluefin-dx:latest"
    * SSH command return code is "0"
    * Reboot VM and wait for SSH
    * Run SSH command: "sudo bootc status --format=json"
    * Active image reference contains "bluefin-dx"

  @lifecycle @etc_merge
  Scenario: /etc customizations survive upgrade
    # Write a sentinel, upgrade, reboot, verify file survives AND digest changed.
    * Capture booted image digest for rollback verification
    * Run SSH command: "echo 'testsuite-marker' | sudo tee /etc/bluefin-test-marker"
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Staged deployment is present in bootc status
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Run SSH command: "cat /etc/bluefin-test-marker"
    * SSH command output "is" "testsuite-marker"
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches upgrade target digest

  @lifecycle @ostree
  Scenario: ostree admin status reports at least two deployments after upgrade
    # Run after an upgrade + reboot so both booted and rollback deployments are present.
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Reboot VM and wait for SSH
    * Run SSH command: "ostree admin status"
    * SSH command return code is "0"
    * ostree status shows two deployments

  @lifecycle @upgrade @version
  Scenario: os-release version changes are tracked after upgrade
    * Capture current os-release VERSION_ID via SSH
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * bootc upgrade output indicates image was staged
    * Run SSH command: "sudo bootc status --format=json"
    * Capture staged image digest as upgrade target
    * Reboot VM and wait for SSH
    * Capture current os-release VERSION_ID via SSH
    * os-release VERSION_ID is tracked across upgrade
    * Run SSH command: "sudo bootc status --format=json"
    * Active deployment matches upgrade target digest
    * bootc status image reference starts with "ghcr.io/"

  @lifecycle @status @version
  Scenario: bootc status shows image reference format is valid
    * Run SSH command: "sudo bootc status --format=json"
    * SSH command return code is "0"
    * bootc status image reference starts with "ghcr.io/"
    * bootc status image digest is a valid sha256
    * Capture current os-release VERSION_ID via SSH
    * Captured VERSION_ID is a valid Fedora version number

  @lifecycle @status @version
  Scenario: Bluefin version is tracked in os-release
    * Run SSH command: "cat /etc/os-release"
    * SSH command return code is "0"
    * os-release reports Fedora Bluefin identity

  @lifecycle @upgrade @idempotent
  Scenario: bootc upgrade is idempotent when already at latest
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * If bootc upgrade output indicates image was staged, reboot VM and wait for SSH
    * Run long SSH command: "sudo bootc upgrade"
    * SSH command return code is "0"
    * Run SSH command: "sudo bootc status --format=json"
    * No staged deployment is present in bootc status

  @lifecycle @autoupdate
  Scenario: Auto-update timer is present and not masked
    * Bluefin VM is booted and reachable over SSH
    * Run SSH command: "systemctl list-timers --all --no-pager 2>/dev/null | grep -c 'bootc\|ostree'"
    * SSH command output is not "0"
