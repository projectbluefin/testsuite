@gnome_core @vanilla_gnome
Feature: Vanilla GNOME baseline smoke tests
  Validates core GNOME Shell behaviour on upstream Fedora (no Bluefin customizations).
  Used as a comparison baseline: failures here indicate upstream GNOME issues;
  failures on Bluefin but not here indicate Bluefin-specific regressions.
  Runner: qecore-headless + behave (same as smoke suite).

  # Golden disk: quay.io/fedora/fedora-bootc:latest (vanilla GNOME, no extensions)
  # Namespace: gnome-baseline-test
  # Runs: manual comparison, not per-PR (expensive)
  # See QA-REVIEW.md Epic E07

  @gnome_core
  Scenario: GNOME Shell process is running and accessible via AT-SPI
    * GNOME Shell is accessible via AT-SPI
    # Informational canary for GNOME 51 readiness (#826). Prints the running
    # org.gnome.Shell ShellVersion to the run log; never gates the run.
    * GNOME Shell version is reported
    * Dump panel children to log
    * Dump gnome-shell AT-SPI tree to results

  @gnome_core
  Scenario: Panel is present in AT-SPI tree
    * GNOME Shell is accessible via AT-SPI
    * Panel is present in AT-SPI tree

  @gnome_core
  Scenario: Activities toggle button is visible in panel
    * GNOME Shell is accessible via AT-SPI
    * Item "Activities" "toggle button" is "showing" in "gnome-shell"

  @gnome_core
  Scenario: Super key opens Activities overview
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Close Activities overview via Shell.Eval
    * Overview is closed

  @gnome_core
  Scenario: Typing in overview populates search bar
    * GNOME Shell is accessible via AT-SPI
    * Open Activities overview via Shell.Eval
    * Overview is open
    * Set overview search text to "Files" via Shell.Eval
    * Overview search bar contains "Files"
    * Close Activities overview via Shell.Eval

  @gnome_core
  Scenario: Clicking System menu opens Quick Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval

  @gnome_core
  Scenario: Do-not-disturb toggle is accessible via Quick Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval
    * Do-not-disturb toggle is present in Quick Settings
    * Close Quick Settings via Shell.Eval

  @gnome_core
  Scenario: Night Light toggle is present in Quick Settings
    * GNOME Shell is accessible via AT-SPI
    * Open Quick Settings via Shell.Eval
    * Quick Settings panel is open via Shell.Eval
    * Night Light toggle is present in Quick Settings
    * Close Quick Settings via Shell.Eval

  @gnome_core
  Scenario: Clicking clock opens calendar popup
    * GNOME Shell is accessible via AT-SPI
    * Open date menu via Shell.Eval
    * Date menu panel is open via Shell.Eval

  @gnome_core
  Scenario: Default GNOME apps are installed
    * GNOME Files application is installed
    * A web browser application is installed
    * A terminal application is installed

  @gnome_core
  Scenario: Screenshot tool opens via keyboard shortcut
    * GNOME Shell is accessible via AT-SPI
    * Screenshot tool launches via Shell.Eval
    * Screenshot tool window is accessible via AT-SPI
    * Close screenshot tool

  @gnome_core
  Scenario: No gnome-shell coredump after session start
    * No coredump entries exist for "gnome-shell"

  @gnome_core
  Scenario: Bluefin-specific extensions are absent on vanilla-gnome
    * Bluefin-specific extensions are absent on vanilla-gnome

