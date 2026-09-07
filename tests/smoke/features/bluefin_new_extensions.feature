@smoke_suite
Feature: Newly enabled Bluefin GNOME extension stability
  Validates curated extensions enabled by default in Bluefin/Dakota
  (projectbluefin/common#1087) are present, interactive, and do not
  destabilize GNOME Shell. Complements the presence-only checks in
  bluefin_extensions.feature with AT-SPI interaction and crash-regression
  coverage for the highest-risk additions.

  @extensions @atspi @priority-high
  Scenario: Copyous clipboard manager is enabled and stable under clipboard stress
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "copyous@boerdereinar.dev" is enabled
    * Clipboard history popover is accessible and interactive via AT-SPI
    * Clipboard history entries can be created, listed, selected, and pasted
    * Rapid clipboard-change events with varied data are handled
    * GNOME Shell remains accessible and does not crash during the stress run
    * GNOME Shell memory usage remains bounded after repeated copy and paste operations

  @extensions
  Scenario: Syncthing Toggle Quick Settings control is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "syncthing-toggle@rehhouari.github.com" is enabled
    * Quick Settings contains a toggle labeled "Sync Folder"
    * The pill and header use the label "Sync Folder"
    * The toggle starts and stops the Syncthing service without shell errors
    * The extension honors "start-stop-only = true"

  @extensions
  Scenario: Bluetooth Battery Meter handles panel and missing-device states
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "Bluetooth-Battery-Meter@maniacx.github.com" is enabled
    * The Bluetooth battery panel icon is rendered
    * The extension uses symbolic indicator color with "level-indicator-color = 0"
    * The panel remains clean and GNOME Shell remains accessible when no Bluetooth devices are present

  @extensions
  Scenario: Quick Settings audio device hider is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "quicksettings-audio-devices-hider@marcinjahn.com" is enabled
    * The Quick Settings audio menu populates cleanly with unwanted devices hidden

  @extensions
  Scenario: Quick Settings audio device renamer is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "quicksettings-audio-devices-renamer@marcinjahn.com" is enabled
    * The Quick Settings audio menu populates cleanly with configured device names applied

  @extensions
  Scenario: Tiling Assistant handles snapping shortcuts and gestures
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "tiling-assistant@leleat-on-github" is enabled
    * Window-snapping keyboard shortcuts work
    * Window-snapping gestures work
    * GNOME Shell remains responsive without shell errors

  @extensions
  Scenario: Tailscale Quick Settings control handles daemon state
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "tailscale-gnome-qs@tailscale-qs.github.io" is enabled
    * Quick Settings contains the Tailscale item and status
    * Running, stopped, and unavailable tailscaled states are handled cleanly
    * GNOME Shell remains accessible without extension errors
