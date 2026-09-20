@software_suite
Feature: Bazaar CLI validation for Bluefin
  Validates Bazaar (io.github.kolunmi.Bazaar) Flatpak presence and metadata
  without requiring AT-SPI GUI access. These scenarios run on Bluefin images
  only — gnomeos and images that do not ship Bazaar are skipped via the
  _has_bazaar() guard in environment.py.

  Replaces the @pending placeholder from issue #419. AT-SPI-based Bazaar
  navigation scenarios remain `@future` in flatpak.feature pending GNOME 51
  AT-SPI re-validation (#847).

  @software @bazaar
  Scenario: Bazaar is installed
    * Flatpak app "io.github.kolunmi.Bazaar" is installed

  @software @bazaar
  Scenario: Bazaar app info is queryable
    * Flatpak app info is queryable for "io.github.kolunmi.Bazaar"

  @software @bazaar
  Scenario: Bazaar is sourced from Flathub
    * Flatpak app "io.github.kolunmi.Bazaar" is from remote "flathub"
