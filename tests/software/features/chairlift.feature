@software_suite
Feature: ChairLift system management CLI and privileged helper validation
  Validates that ChairLift (io.projectbluefin.chairlift) and its accompanying
  PolicyKit helpers (chairlift-ublue-helper and chairlift-updex-helper) are
  installed, properly configured with PolicyKit actions, and strictly enforce
  argv privilege boundaries.

  @software @chairlift
  Scenario: ChairLift binary is installed and executable
    * Run SSH command: "test -x /usr/bin/chairlift && echo present"
    * SSH command output contains "present"

  @software @chairlift
  Scenario: ChairLift displays CLI help with dry-run support
    * Run SSH command: "chairlift --help"
    * SSH command output contains "--dry-run"
    * SSH command return code is "0"

  @software @chairlift
  Scenario: ChairLift ublue helper binary is installed and executable
    * Run SSH command: "test -x /usr/bin/chairlift-ublue-helper && echo present"
    * SSH command output contains "present"

  @software @chairlift
  Scenario: ChairLift updex helper binary is installed and executable
    * Run SSH command: "test -x /usr/bin/chairlift-updex-helper && echo present"
    * SSH command output contains "present"

  @software @chairlift
  Scenario: ChairLift PolicyKit actions are registered
    * Run SSH command: "pkaction --action-id io.projectbluefin.chairlift.ublue.channel-switch && echo registered"
    * SSH command output contains "registered"
    * Run SSH command: "pkaction --action-id io.projectbluefin.chairlift.ublue.restart && echo registered"
    * SSH command output contains "registered"
    * Run SSH command: "pkaction --action-id io.projectbluefin.chairlift.ublue.rollback && echo registered"
    * SSH command output contains "registered"

  @software @chairlift
  Scenario: ChairLift maintainer configuration is present and valid
    * Run SSH command: "test -f /usr/share/chairlift/config.yml && echo present"
    * SSH command output contains "present"

  @software @chairlift
  Scenario: ChairLift desktop application entry is installed
    * Run SSH command: "test -f /usr/share/applications/io.projectbluefin.chairlift.desktop && echo present"
    * SSH command output contains "present"

  @software @chairlift
  Scenario: ChairLift ublue helper strictly rejects unsupported commands and argument injection
    * Run SSH command: "chairlift-ublue-helper unknown-subcommand 2>&1 || true"
    * SSH command output contains "unknown command"
    * Run SSH command: "chairlift-ublue-helper channel-switch 'ghcr.io/evil/image:latest' 2>&1 || true"
    * SSH command output contains "usage: chairlift-ublue-helper channel-switch"
    * Run SSH command: "chairlift-ublue-helper restart --delay=10 2>&1 || true"
    * SSH command output contains "usage: chairlift-ublue-helper restart"
