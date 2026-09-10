@smoke_suite @extensions @copyous
Feature: Copyous clipboard manager crash-regression and stress resilience
  Copyous (copyous@boerdereinar.dev) is known to have caused GNOME Shell crashes,
  black screens, and GDM fallbacks under heavy clipboard activity, binary/large payloads,
  rapid clipboard churn, database corruption, or lifecycle toggling.
  This suite rigorously exercises Copyous under aggressive conditions and verifies
  that GNOME Shell never crashes, leaks memory, throws unhandled GJS exceptions, or dies.

  Background:
    Given GNOME Shell is accessible via AT-SPI
    And GNOME extension "copyous@boerdereinar.dev" is enabled

  @extensions @atspi @priority-high @stress
  Scenario: Copyous survives burst clipboard churn with heterogeneous payloads
    When snapshotting GNOME Shell state and journal marker
    And generating rapid clipboard churn of 40 events with varied MIME types and binary data
    Then the clipboard retains the final copied payload
    And GNOME Shell remains accessible via AT-SPI
    And no gnome-shell coredump or crash occurred
    And no fatal GJS or extension errors exist in the journal

  @extensions @atspi @priority-high @stress
  Scenario: Copyous handles oversized payloads without crashing GNOME Shell or blowing memory limits
    When snapshotting GNOME Shell state and journal marker
    And copying a 1 megabyte payload to clipboard
    And copying a multiline text payload of 5000 lines to clipboard
    And copying complex nested JSON payload to clipboard
    Then GNOME Shell remains responsive within 3 seconds
    And GNOME Shell memory growth remains strictly bounded under 200 megabytes
    And no gnome-shell coredump or crash occurred

  @extensions @atspi @priority-high @stress
  Scenario: Copyous popover rapid open close and keyboard navigation does not freeze the compositor
    When Copyous clipboard history popover is opened via keyboard shortcut or AT-SPI
    And Copyous clipboard history popover is rapidly toggled 10 times
    Then GNOME Shell remains accessible via AT-SPI
    And GNOME Shell responds to Shell.Eval within 2 seconds
    And no gnome-shell coredump or crash occurred

  @extensions @atspi @lifecycle @regression
  Scenario: Copyous survives rapid enable disable lifecycle stress without crashing GNOME Shell
    When snapshotting GNOME Shell state and journal marker
    And GNOME extension "copyous@boerdereinar.dev" is disabled
    And GNOME Shell responds to Shell.Eval within 2 seconds
    And GNOME extension "copyous@boerdereinar.dev" is re-enabled
    And GNOME Shell responds to Shell.Eval within 2 seconds
    Then GNOME Shell remains accessible via AT-SPI
    And no gnome-shell coredump or crash occurred
    And no fatal GJS or extension errors exist in the journal

  @extensions @atspi @persistence @stress
  Scenario: Copyous database and history persistence withstands empty and null byte payloads
    When snapshotting GNOME Shell state and journal marker
    And copying payload with embedded null bytes and escape characters
    And copying an empty string payload
    And copying payload with special characters and SQL injection strings
    Then the clipboard retains the final copied payload
    And GNOME Shell remains accessible via AT-SPI
    And no gnome-shell coredump or crash occurred
