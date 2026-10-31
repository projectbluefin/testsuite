@smoke_suite @dakota_only
Feature: Dakota desktop identity
  Validates Dakota-specific desktop components that differ from Bluefin and
  must remain present for basic usability.

  @dakota_only
  Scenario: ghostty is available as Dakota's terminal
    * Run command on VM: "ghostty --version"
    * VM command return code is "0"

  @dakota_only
  Scenario: sudo-rs provides the sudo command
    * Run command on VM: "sudo --version"
    * VM command return code is "0"
    * VM command output contains "sudo-rs"

  @dakota_only
  Scenario: Homebrew is preinstalled
    * Run command on VM: "brew --version"
    * VM command return code is "0"

  @dakota_only
  Scenario: distrobox is available
    * Run command on VM: "distrobox --version"
    * VM command return code is "0"

  @dakota_only
  Scenario: Bazaar Integration extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "bazaar-integration@kolunmi.github.io" is enabled
