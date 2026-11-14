@smoke_suite
Feature: GNOME 51 audit probe 3 (#827, temporary)
  Records, without asserting them, the readings that decide whether audit rows
  4, 5, 6 and 10 are still needed on GNOME 51: what each workaround guards,
  measured on the path the workaround replaced.

  @gnome51_audit_probe
  Scenario: Record GNOME 51 audit probe 3 app readings
    * GNOME Shell is accessible via AT-SPI
    * Record GNOME 51 audit probe 3 qecore version
    * Launch GNOME 51 audit probe 3 apps
    * Record GNOME 51 audit probe 3 rows 4 and 6 application toplevels
    * Record GNOME 51 audit probe 3 row 5 Files sidebar roles

  @gnome51_audit_probe
  Scenario: Record GNOME 51 audit probe 3 notification banner
    * GNOME Shell is accessible via AT-SPI
    * A test desktop notification is sent via gdbus
    * Record GNOME 51 audit probe 3 row 10 banner while showing
    * Dismiss the notification via gdbus CloseNotification
    * Record GNOME 51 audit probe 3 row 10 banner after dismissal

  @gnome51_audit_probe
  Scenario: Record GNOME 51 audit probe 3 banner after an immediate close
    * GNOME Shell is accessible via AT-SPI
    * A test desktop notification is sent via gdbus
    * Notification request returns a positive notification ID
    * Dismiss the notification via gdbus CloseNotification
    * Record GNOME 51 audit probe 3 row 10 banner after dismissal

  @gnome51_audit_probe
  Scenario: Record GNOME 51 audit probe 3 banner owner and idle hold
    * GNOME Shell is accessible via AT-SPI
    * A test desktop notification is sent via gdbus
    * Record GNOME 51 audit probe 3 row 10 banner owner "sent"
    * Dismiss the notification via gdbus CloseNotification
    * Record GNOME 51 audit probe 3 row 10 banner owner "closed"
    * Key combo: "<Shift>" with uinput
    * Record GNOME 51 audit probe 3 row 10 banner owner "after-input"
