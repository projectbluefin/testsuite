@native_app @smoke_suite
Feature: GNOME Calculator smoke tests
  Validates GNOME Calculator launches, performs simple arithmetic, resets
  state cleanly, and exits without crashes on a fresh Bluefin session.

  Background:
    * Launch Calculator via command

  @retry @calculator @launch @sla_15s
  Scenario: Calculator launches and window is accessible
    * Calculator window is accessible

  @calculator @addition
  Scenario: Basic addition
    * Calculator window is accessible
    * Click calculator button "1"
    * Click calculator button "+"
    * Click calculator button "2"
    * Click calculator button "="
    * Calculator display shows "3"

  @calculator @subtraction
  Scenario: Basic subtraction
    * Calculator window is accessible
    * Click calculator button "9"
    * Click calculator button "-"
    * Click calculator button "4"
    * Click calculator button "="
    * Calculator display shows "5"

  @calculator @clear
  Scenario: Clear button resets display
    * Calculator window is accessible
    * Click calculator button "8"
    * Click calculator button "+"
    * Click calculator button "1"
    * Calculator display shows "8+1"
    * Clear calculator display
    * Calculator display is cleared

  @calculator @multiplication
  Scenario: Basic multiplication
    * Calculator window is accessible
    * Click calculator button "6"
    * Click calculator button "×"
    * Click calculator button "7"
    * Click calculator button "="
    * Calculator display shows "42"

  @calculator @division
  Scenario: Basic division
    * Calculator window is accessible
    * Click calculator button "9"
    * Click calculator button "÷"
    * Click calculator button "3"
    * Click calculator button "="
    * Calculator display shows "3"

  @calculator @decimal
  Scenario: Decimal arithmetic
    * Calculator window is accessible
    * Click calculator button "1"
    * Click calculator button "."
    * Click calculator button "5"
    * Click calculator button "+"
    * Click calculator button "1"
    * Click calculator button "."
    * Click calculator button "5"
    * Click calculator button "="
    * Calculator display shows "3"

  @calculator @negative
  Scenario: Subtracting to a negative result
    * Calculator window is accessible
    * Click calculator button "3"
    * Click calculator button "-"
    * Click calculator button "8"
    * Click calculator button "="
    * Calculator display shows "-5"

  @calculator @close
  Scenario: Calculator closes cleanly via Ctrl+Q
    * Calculator window is accessible
    * Key combo: "<Ctrl><Q>" with uinput
    * Calculator is no longer running

  @calculator @coredump @regression @bluefin
  Scenario: No gnome-calculator coredump after session start
    * No coredump entries exist on the host for "gnome-calculator"
