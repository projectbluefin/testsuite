@smoke_suite
Feature: GNOME 51 audit probe 2 (#827, temporary)
  Records, without asserting them, the GNOME 51 audit rows no passing
  scenario measures: 1, 2, 3, 7, 8, 12 and the clock and System toggles of
  row 11. Sorted last so the screen-lock probe runs after everything else.

  @gnome51_audit_probe
  Scenario: Record GNOME 51 audit probe 2 readings
    * GNOME Shell is accessible via AT-SPI
    * Record GNOME 51 audit probe 2 version
    * Record GNOME 51 audit probe 2 row 2 Shell.Eval result format
    * Record GNOME 51 audit probe 2 row 1 unsafe_mode across UI events
    * Record GNOME 51 audit probe 2 row 3 extension state
    * Record GNOME 51 audit probe 2 row 7 Ptyxis window title
    * Record GNOME 51 audit probe 2 row 11 clock and System toggles
    * Record GNOME 51 audit probe 2 row 12 keyring without qecore keyring setup
    * Record GNOME 51 audit probe 2 row 8 screen lock paths
