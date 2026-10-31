@smoke_suite @compass
Feature: Compass launcher
  Compass (org.tunaos.compass) is preinstalled from FlatPark and bound to
  Super+Space through a GNOME custom keybinding.

  Scenario: Compass launcher Flatpak is preinstalled
    * Compass Flatpak is installed system-wide within 600 seconds

  Scenario: Super+Space toggles the Compass launcher
    * Compass Flatpak is installed system-wide within 600 seconds
    * Compass user service is wanted by graphical-session.target
    * Compass user service is stopped and its engine is gone within 30 seconds
    * Compass user service is started with one serving engine within 60 seconds
    * Compass user service is restarted with one serving engine within 60 seconds
    * GNOME Shell is accessible via AT-SPI
    * Key combo: "<Super>space"
    * Compass diagnostics are logged
    * Compass launcher window is visible within 60 seconds
    * Key combo: "<Super>space"
    * Compass launcher window is hidden within 30 seconds
