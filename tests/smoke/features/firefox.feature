@smoke_suite @bluefin
Feature: Firefox smoke tests
  Validates Firefox launches in the desktop session without crashing.

  @retry @firefox @launch @close @regression @sla_90s
  Scenario: Firefox launches without crashing
    * Launch Firefox via command
    * Firefox main window is accessible
    * No coredump entries exist on the host for "firefox"
