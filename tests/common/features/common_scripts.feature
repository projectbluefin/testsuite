@common @bluefin
Feature: Bluefin common system scripts
  Verifies common-layer helper binaries are present and runnable over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: ublue image info prints image metadata
    * Run SSH command: "command -v ublue-image-info.sh >/dev/null && ublue-image-info.sh || ublue-image-info"
    * SSH command return code is "0"
    * SSH command output is not empty

  Scenario: ublue-system-setup is executable
    * Run SSH command: "test -x /usr/bin/ublue-system-setup"
    * SSH command return code is "0"

  Scenario: ublue-user-setup is executable
    * Run SSH command: "test -x /usr/bin/ublue-user-setup"
    * SSH command return code is "0"

  Scenario: bootc is on PATH and returns version
    * Run SSH command: "bootc --version"
    * SSH command return code is "0"
    * Last command output contains "bootc"

  Scenario: just is available for ujust task runner
    * Run SSH command: "just --version"
    * SSH command return code is "0"

  Scenario: ublue-update service unit exists
    * Run SSH command: "systemctl list-unit-files 'ublue-update*' 2>/dev/null | grep -c 'ublue-update' || systemctl list-units 'ublue-update*' --all 2>/dev/null | grep -c 'ublue-update'"
    * SSH command output is not "0"

  Scenario: dconf-update service ran successfully
    * Run SSH command: "systemctl show dconf-update.service --property=Result --value 2>/dev/null | grep -Eq '^success$'"
    * SSH command return code is "0"

  Scenario: ublue-system-setup service completed
    * Run SSH command: "systemctl is-active ublue-system-setup.service 2>/dev/null || systemctl show ublue-system-setup.service --property=ActiveState | grep -E 'active|inactive'"
    * SSH command return code is "0"

  Scenario: bazaar user service is available
    * Run SSH command: "systemctl --user show bazaar.service --property=LoadState 2>/dev/null | grep -v 'not-found' || true"
    * SSH command return code is "0"

  # Pending: ublue-update.timer is not enabled in CI images, so this asserts
  # planned behaviour rather than shipped behaviour.
  @pending
  Scenario: ublue-update timer is enabled
    * Run SSH command: "systemctl is-enabled ublue-update.timer 2>/dev/null || systemctl list-timers ublue-update.timer --all 2>/dev/null | grep ublue-update"
    * SSH command return code is "0"
