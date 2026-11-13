@smoke_suite
Feature: GNOME 51 audit probe (#827, temporary)
  Records, without asserting them, the two properties the GNOME 51 audit
  rows 9 and 11 could not measure from passing scenarios.

  @gnome51_audit_probe
  Scenario: Record Main.overview.visible and panel button showing across an overview toggle
    * GNOME Shell is accessible via AT-SPI
    * Record GNOME 51 audit probe across an overview toggle
