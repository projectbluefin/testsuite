@smoke_suite
Feature: Newly enabled Bluefin GNOME extension stability
  Validates curated extensions enabled by default in Bluefin/Dakota
  (projectbluefin/common#1087) are present, interactive, and do not
  destabilize GNOME Shell. Complements the presence-only checks in
  bluefin_extensions.feature with AT-SPI interaction coverage.

  @extensions @pending
  # @pending: 'The Bluetooth battery panel icon is rendered' soft-passes when
  # dogtail is unavailable or gnome-shell is absent from the AT-SPI tree.
  Scenario: Bluetooth Battery Meter handles panel and missing-device states
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "Bluetooth-Battery-Meter@maniacx.github.com" is enabled
    * The Bluetooth battery panel icon is rendered
    * The extension uses symbolic indicator color with "level-indicator-color = 0"
    * The panel remains clean and GNOME Shell remains accessible when no Bluetooth devices are present

  @extensions @pending
  # @pending: 'Window-snapping keyboard shortcuts work' soft-passes when uinput
  # key injection is unavailable, which is the normal CI case.
  Scenario: Tiling Assistant handles snapping shortcuts and gestures
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "tiling-assistant@leleat-on-github" is enabled
    * Window-snapping keyboard shortcuts work
    * Window-snapping gestures work
    * GNOME Shell remains responsive without shell errors

