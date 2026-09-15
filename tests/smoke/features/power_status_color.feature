@smoke_suite @extensions @power_status
Feature: Power Status Color extension alerts
  The power-status-color GNOME Shell extension (bluefin-bling) recolours the
  Quick Settings power button to surface maintenance state:
    - yellow `power-status-reboot`  when /run/reboot-required exists or a
      staged `bootc` update is queued,
    - red `power-status-overdue`    when host uptime reaches 30+ days (takes
      precedence over yellow),
    - default styling              otherwise.

  NOTE (issue #794): the issue spec proposed the UUID `power-status-color@local`
  and class names `bootc-reboot-required` / `bootc-uptime-overdue`. The
  extension actually ships (bluefin-bling metadata.json / extension.js) with
  UUID `power-status-color@projectbluefin.io` and class names
  `power-status-reboot` / `power-status-overdue`; these tests assert the real
  shipped contract. The 30-day uptime branch cannot be reproduced in CI, so the
  red-alert class is only asserted to be absent at teardown.
  Runner: qecore-headless + behave (same as smoke suite).
  Image: ghcr.io/projectbluefin/bluefin:latest

  Background:
    * GNOME Shell is accessible via AT-SPI

  @power_status
  Scenario: Power status color extension is enabled
    * GNOME extension "power-status-color@projectbluefin.io" is enabled

  @power_status @retry
  Scenario: Power button indicates reboot required when flag file exists
    Given file "/run/reboot-required" is removed
    When file "/run/reboot-required" is created
    Then Quick Settings power button has CSS class "power-status-reboot" within 2 seconds
    When file "/run/reboot-required" is removed
    Then Quick Settings power button does not have CSS class "power-status-reboot" within 2 seconds

  @power_status @retry
  Scenario: Power status color extension cleans up on disable
    Given file "/run/reboot-required" is created
    And Quick Settings power button has CSS class "power-status-reboot" within 2 seconds
    When GNOME extension "power-status-color@projectbluefin.io" is disabled
    Then Quick Settings power button has no custom power alert classes
    When file "/run/reboot-required" is removed
    When GNOME extension "power-status-color@projectbluefin.io" is enabled again