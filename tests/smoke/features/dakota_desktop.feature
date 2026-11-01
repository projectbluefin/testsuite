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

  # CI masks brew-setup.service at boot, so brew is never unpacked in this lane;
  # check the shipped payload and unit. The startup lane checks the unpacked brew.
  @dakota_only
  Scenario: Homebrew ships with its first-boot setup service
    * Run command on VM: "test -f /usr/share/homebrew.tar.zst && test -f /usr/lib/systemd/system/brew-setup.service"
    * VM command return code is "0"

  @dakota_only
  Scenario: distrobox is available
    * Run command on VM: "distrobox --version"
    * VM command return code is "0"

  @dakota_only
  Scenario: Bazaar Integration extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "bazaar-integration@kolunmi.github.io" is enabled
