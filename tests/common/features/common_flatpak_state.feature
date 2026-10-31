@common @bluefin
Feature: Flatpak first-boot state
  Verifies Bluefin's Flatpak remote configuration after first boot.
  Bluefin ships with Flathub as the sole Flatpak remote.
  Note: flatpak-preinstall.service is masked in CI; app presence is not checked.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # Pending: /var is not preserved from the OCI build, so /var/lib/flatpak state
  # (including remotes) is empty on a fresh CI install.
  @pending
  Scenario: Flathub remote is configured
    * Run SSH command: "flatpak remote-list --columns=name 2>/dev/null | grep -w flathub"
    * SSH command return code is "0"
    * Last command output contains "flathub"

  Scenario: Fedora Flatpak remote is absent
    * Run SSH command: "flatpak remote-list --columns=name 2>/dev/null"
    * SSH command return code is "0"
    * SSH command output does not contain "fedora"

  Scenario: flatpak command is available
    * Run SSH command: "flatpak --version"
    * SSH command return code is "0"
    * SSH command output is not empty

  Scenario: flatpak user installations directory exists
    * Run SSH command: "test -d /var/home/$(id -un)/.local/share/flatpak 2>/dev/null || test -d /root/.local/share/flatpak"
    * SSH command return code is "0"
