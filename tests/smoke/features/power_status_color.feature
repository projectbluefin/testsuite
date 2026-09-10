@native_app @smoke_suite
Feature: Power status color extension alerts
  Validates the power-status-color@projectbluefin.io GNOME Shell extension
  (projectbluefin/bluefin-bling) correctly alters the Quick Settings power
  button styling in reaction to a staged bootc update / reboot-required
  flag and to high system uptime, honors alert precedence, and tears down
  cleanly on disable.

  @extensions @power_status
  Scenario: Power status color extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "power-status-color@projectbluefin.io" is enabled
    * No gnome-shell extension load journal errors exist
    * No power-status-color extension GJS or St warnings exist in the journal

  @extensions @power_status @atspi
  Scenario: Power button indicates reboot required when flag file exists
    Given GNOME Shell is accessible via AT-SPI
    And GNOME extension "power-status-color@projectbluefin.io" is enabled
    When file "/run/reboot-required" is created on the host
    Then Quick Settings power button has style class "power-status-reboot" within 5 seconds
    When file "/run/reboot-required" is removed from the host
    Then Quick Settings power button does not have style class "power-status-reboot" within 5 seconds

  @extensions @power_status
  Scenario: Uptime overdue alert takes precedence over reboot required
    Given GNOME Shell is accessible via AT-SPI
    And GNOME extension "power-status-color@projectbluefin.io" is enabled
    And file "/run/reboot-required" is created on the host
    And Quick Settings power button has style class "power-status-reboot" within 5 seconds
    When the power status color extension simulates uptime overdue and re-evaluates status
    Then Quick Settings power button has style class "power-status-overdue"
    And Quick Settings power button does not have style class "power-status-reboot"
    When the power status color extension stops simulating uptime overdue and re-evaluates status
    And file "/run/reboot-required" is removed from the host
    Then Quick Settings power button has no power status alert style classes

  @extensions @power_status @regression
  Scenario: Extension cleans up style classes and timers on disable
    Given GNOME Shell is accessible via AT-SPI
    And GNOME extension "power-status-color@projectbluefin.io" is enabled
    And file "/run/reboot-required" is created on the host
    And Quick Settings power button has style class "power-status-reboot" within 5 seconds
    When GNOME extension "power-status-color@projectbluefin.io" is disabled
    Then Quick Settings power button has no power status alert style classes
    And the power status color extension has no active file monitor or timer
    When file "/run/reboot-required" is removed from the host
    And GNOME extension "power-status-color@projectbluefin.io" is re-enabled
    Then Quick Settings power button has no power status alert style classes
