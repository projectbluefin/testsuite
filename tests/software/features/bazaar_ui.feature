@software_suite
Feature: Bazaar UI accessibility for Bluefin
  Validates Bazaar (`io.github.kolunmi.Bazaar`) launches and exposes its
  actual Adwaita UI structure on Bluefin images. Scenarios skip automatically
  on images without Bazaar via the existing _has_bazaar() guard.

  Background:
    * Launch Bazaar
    * Bazaar main window is accessible
    * Bazaar main content is loaded

  @retry @software @bazaar_ui @launch
  Scenario: Bazaar launches and main window is accessible
    * Bazaar main window is accessible
    * Bazaar main content is loaded

  @retry @software @bazaar_ui @navigation
  Scenario: Library tab is accessible
    * Bazaar tab "Library" is accessible
    * Activate Bazaar tab "Library"
    * Bazaar view "Library" is loaded

  @retry @software @bazaar_ui @navigation
  Scenario: Explore tab is accessible
    * Bazaar tab "Explore" is accessible
    * Activate Bazaar tab "Explore"
    * Bazaar view "Explore" is loaded

  @retry @software @bazaar_ui @close
  Scenario: Bazaar closes cleanly
    * Close Bazaar via shortcut
    * Bazaar is no longer running
    * No coredump entries exist on the VM for "bazaar"
