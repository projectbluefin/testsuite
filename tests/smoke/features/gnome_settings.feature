@native_app @smoke_suite
Feature: GNOME Settings smoke tests
  Validates GNOME Settings launches, exposes core navigation, and shows
  Bluefin system information without crashing.

  Background:
    * Launch Settings via command
    * Settings window is accessible

  @retry @settings @launch @sla_15s
  Scenario: GNOME Settings launches and window is accessible
    * Settings window is accessible

  @settings @navigation
  Scenario: Settings sidebar is present with navigation items
    * Settings sidebar is present

  @settings @about
  Scenario: About page is accessible
    * Navigate to Settings panel "About"
    * Settings panel "About" is visible

  @settings @about
  Scenario: About page shows OS information
    * Navigate to Settings panel "About"
    * Settings panel "About" is visible
    * About page shows system information

  @settings @displays
  Scenario: Displays settings panel is accessible
    * Navigate to Settings panel "Displays"
    * Settings panel "Displays" is visible

  @settings @wifi
  Scenario: Wi-Fi settings panel is accessible
    * Navigate to Settings panel "Wi-Fi"
    * Settings panel "Wi-Fi" is visible

  @settings @privacy
  Scenario: Privacy settings panel is accessible
    * Navigate to Settings panel "Privacy & Security"
    * Settings panel "Privacy & Security" is visible

  @settings @notifications
  Scenario: Notifications settings panel is accessible
    * Navigate to Settings panel "Notifications"
    * Settings panel "Notifications" is visible

  @settings @keyboard
  Scenario: Keyboard settings panel is accessible
    * Navigate to Settings panel "Keyboard"
    * Settings panel "Keyboard" is visible

  # QEMU without power-supply hardware: PowerProfiles activation times out
  # before Settings registers on AT-SPI (testsuite#1153). Keep bare-metal coverage
  # and run on VMs that expose a power supply; do not extend the UI timeout.
  @settings @power @requires_vm_power_supply
  Scenario: Power settings panel is accessible
    * Navigate to Settings panel "Power"
    * Settings panel "Power" is visible

  @settings @accessibility
  Scenario: Accessibility settings panel is accessible
    * Navigate to Settings panel "Accessibility"
    * Settings panel "Accessibility" is visible

  @settings @close
  Scenario: Settings closes cleanly via Ctrl+Q
    * Key combo: "<Ctrl><Q>" with uinput
    * Settings is no longer running
