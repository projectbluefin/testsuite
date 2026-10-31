@software_suite
Feature: Upstream GNOME Software smoke tests (planned, #847)
  Planned coverage for images that ship GNOME Software (`org.gnome.Software`).
  Bluefin, Dakota and Utah ship Bazaar instead; their coverage lives in
  bazaar_ui.feature and bazaar_navigation.feature. Regression coverage for
  bluefin#4062 and #4471.

  Every scenario is @future: nothing registers a qecore "software"
  application, and environment.py gates @software scenarios on Bazaar, not
  GNOME Software. Before un-futuring, register the app in before_all and gate
  these scenarios on GNOME Software being installed.

  Background:
    * Start application "software" via "command"
    * Wait until "Software" "frame" appears in "software"

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
  Scenario: GNOME Software closes cleanly via shortcut
    * Close application "software" via "shortcut"
    * Application "software" is no longer running

  # Flatpak CLI checks live in flatpak_cli.feature, which has no Background
  # dependency, so they run cleanly on all images.
