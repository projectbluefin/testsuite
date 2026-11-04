@gnomeos_canary
Feature: GNOME OS desktop automation prerequisites
  This baseline runs no candidate extensions. It proves that input injected into
  a real Wayland window can be read back through the guest accessibility bus.

  Scenario: Virtual keyboard input reaches an accessible GNOME OS window
    Given the guest is a genuine GNOME OS Wayland desktop
    When virtual input types into the canary window
    Then accessibility reports the exact text and desktop evidence is saved
