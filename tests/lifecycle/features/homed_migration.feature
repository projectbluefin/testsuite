@homed_migration @lifecycle
Feature: systemd-homed migration — traditional user survives dakota:testing → dakota:next
  Validates that a traditional /etc/passwd user is preserved and functional
  when switching from dakota:testing to a homed-enabled dakota:next image via
  bootc switch.

  The migration target is parameterised via the MIGRATION_TARGET env var
  and is required: with it unset the switch step fails instead of falling
  back to the Bluefin default. dakota:next is paused, so pass the
  homed-enabled Dakota ref explicitly.

  Steps that require systemd-homed to be active on the target image skip
  gracefully when homed is absent, so this suite is safe to run against any
  dakota tag.

  Background:
    * Bluefin VM is booted and reachable over SSH

  @homed_migration @service
  Scenario: systemd-homed is active after bootc switch to a homed-enabled image
    * Switch to required migration target
    * SSH command return code is "0"
    * Run SSH command: "sudo bootc status --format=json"
    * Staged deployment is present in bootc status
    * Reboot VM and wait for SSH after migration
    * systemd-homed service is active after migration

  @homed_migration @user
  Scenario: Traditional /etc/passwd user resolves via id after homed migration
    * Switch to required migration target
    * SSH command return code is "0"
    * Reboot VM and wait for SSH after migration
    * Traditional user is resolvable via id after homed migration

  @homed_migration @pam
  Scenario: pam_systemd_home is wired into system-auth after homed migration
    * Switch to required migration target
    * SSH command return code is "0"
    * Reboot VM and wait for SSH after migration
    * pam_systemd_home is present in system-auth PAM config

  @homed_migration @gdm
  Scenario: GDM shows no authentication failures for traditional user after homed migration
    * Switch to required migration target
    * SSH command return code is "0"
    * Reboot VM and wait for SSH after migration
    * No PAM authentication failures in journal for traditional user
    * GDM journal shows no authentication failures after homed migration

  @homed_migration @homectl
  Scenario: homectl list has no spurious record for the traditional user after migration
    * Switch to required migration target
    * SSH command return code is "0"
    * Reboot VM and wait for SSH after migration
    * homectl list does not contain traditional user entry

  @homed_migration @health
  Scenario: No failed systemd units after homed migration
    * Switch to required migration target
    * SSH command return code is "0"
    * Reboot VM and wait for SSH after migration
    * Run SSH command: "test -z \"$(sudo systemctl list-units --state=failed --no-legend 2>/dev/null)\""
    * SSH command return code is "0"
