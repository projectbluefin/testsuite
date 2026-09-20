@software_suite
Feature: Flatpak CLI smoke tests
  Validates flatpak CLI fundamentals that do not require a GUI app to be running.
  These run on any image that ships flatpak (bluefin, gnomeos, etc.).

  @software @flatpak_cli
  Scenario: Flathub remote is configured and reachable
    * Flatpak remote "flathub" is configured

  @software @flatpak_cli @flatpak_permissions
  Scenario: Flatpak permissions database is queryable
    * Flatpak permissions table "notifications" is queryable

  @software @flatpak_cli @flatpak_permissions
  Scenario: flatpak user override round-trip succeeds
    # Calculator is always present; override doesn't require the app to be installed.
    * Set flatpak user override "--filesystem=home" for "org.gnome.Calculator"
    * Flatpak user override "filesystem=home" is active for "org.gnome.Calculator"
    * Reset flatpak user overrides for "org.gnome.Calculator"
    * No flatpak user overrides exist for "org.gnome.Calculator"

  # Future: Bluefin ships Bazaar rather than GNOME Software, so this belongs to the
  # planned gnomeos/GNOME 51 coverage tracked alongside the other #847 scenarios.
  @future @software @flatpak_cli
  Scenario: flatpak install and uninstall round-trip succeeds
    # Apostrophe (~5 MB) is a small, stable Flatpak with no heavy runtimes.
    # Also deferred to avoid slow network I/O on routine PR runs.
    * Run and save command output: "flatpak install --noninteractive flathub org.gnome.Apostrophe 2>&1; echo rc:$?"
    * Last command output contains "rc:0"
    * Flatpak app "org.gnome.Apostrophe" is installed
    * Run and save command output: "flatpak uninstall --noninteractive org.gnome.Apostrophe 2>&1; echo rc:$?"
    * Last command output contains "rc:0"
    * Flatpak app "org.gnome.Apostrophe" is not installed
