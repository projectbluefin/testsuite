@software_suite
Feature: Bazaar (GNOME Software) smoke tests
  Validates Bazaar (`io.github.kolunmi.Bazaar`) launches and core UI elements are accessible.
  Regression coverage for bluefin#4062 and #4471.

  Background:
    * Start application "software" via "command"
    * Wait until "Software" "frame" appears in "software"

  @software @launch
  Scenario: Bazaar launches and main window is visible
    * Application "software" is running
    * Item "Software" "frame" is "showing" in "software"

  # Future: these target GNOME Software's Explore/Installed widgets, not
  # Bazaar's real AdwViewStack layout. Replaced by bazaar_ui.feature for
  # Bluefin images; retained as planned vanilla-gnome coverage (#847).
  @future @software @navigation
  Scenario: Explore tab is present and accessible
    * Item "Explore" "toggle button" is "showing" in "software"

  @future @software @navigation
  Scenario: Installed tab is present and accessible
    * Item "Installed" "toggle button" is "showing" in "software"

  @future @software @navigation
  Scenario: Clicking Installed tab shows installed apps list
    * Left click "Installed" "toggle button" in "software"
    * Wait until "Installed" "page tab" appears in "software"

  @software @search
  Scenario: Search bar accepts input and returns results
    * Left click "Search" "toggle button" in "software"
    * Type text: "Firefox" with uinput
    * Wait until "Firefox" "label" appears in "software"

  # These crash/close checks also target the old GNOME Software widget model.
  # Replaced by bazaar_ui.feature for Bluefin images; retained as planned
  # upstream GNOME Software coverage on vanilla-gnome images (#847).
  @future @software @regression @bluefin_4062
  Scenario: Flatpak updates section is reachable without crash (bluefin#4062)
    * Left click "Installed" "toggle button" in "software"
    * No journal entries match "gnome-software.*segfault|gnome-software.*abort"

  @future @software @regression @bluefin_4471
  Scenario: No gnome-software coredump on Explore page load (bluefin#4471)
    * Left click "Explore" "toggle button" in "software"
    * Wait 2 seconds before action
    * No coredump entries exist for "gnome-software"

  @future @software @close
  Scenario: Bazaar closes cleanly via shortcut
    * Close application "software" via "shortcut"
    * Application "software" is no longer running

  # ── Flatpak CLI checks moved to flatpak_cli.feature ─────────────────────
  # flatpak_permissions and flatpak_cli scenarios are now in flatpak_cli.feature
  # which has no Background dependency, so they run cleanly on all images.

