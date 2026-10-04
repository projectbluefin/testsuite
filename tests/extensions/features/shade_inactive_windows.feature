@extensions_suite @shade_inactive_windows
Feature: Shade Inactive Windows Reborn dims inactive application windows
  Shading changes compositor brightness rather than window opacity. The focused
  application remains unshaded, excluded applications stay exempt, and disabling
  the extension removes its effects and animations from real window actors.

  Background:
    Given Hive extension "shade-inactive-windows" is installed
    And Shade Inactive Windows is configured for 45 percent shading and a 200 millisecond fade
    And fresh Text Editor and Calculator application windows are open for shading
    When I enable the selected Hive extension

  Scenario: Shading follows focus transferred between two real applications
    When I focus the "Text Editor" application window for shading using keyboard input
    Then the "Text Editor" application window is focused and unshaded
    And the "Calculator" application window is inactive and shaded by 45 percent
    When I focus the "Calculator" application window for shading using keyboard input
    Then the "Calculator" application window is focused and unshaded
    And the "Text Editor" application window is inactive and shaded by 45 percent

  Scenario: Changing shade level at runtime updates inactive brightness without shading the focused window
    When I focus the "Calculator" application window for shading using keyboard input
    Then the "Calculator" application window is focused and unshaded
    And the "Text Editor" application window is inactive and shaded by 45 percent
    And a screenshot records the "Text Editor" window shaded by 45 percent
    When I change the Shade Inactive Windows shade level to 60 percent
    Then the "Text Editor" application window is inactive and shaded by 60 percent
    And the "Calculator" application window is focused and unshaded
    And a screenshot records the "Text Editor" window shaded by 60 percent

  Scenario: An excluded inactive application loses its effect and resumes shading when included
    When I focus the "Text Editor" application window for shading using keyboard input
    Then the "Calculator" application window is inactive and shaded by 45 percent
    When I exclude the "Calculator" application from shading using its window class
    Then the "Calculator" application window is inactive and exempt from shading
    And the "Text Editor" application window is focused and unshaded
    When I clear the Shade Inactive Windows application exclusions
    Then the "Calculator" application window is inactive and shaded by 45 percent
    And the "Text Editor" application window is focused and unshaded

  Scenario: Disabling removes window effects and transitions and re-enabling restores shading
    When I focus the "Calculator" application window for shading using keyboard input
    Then the "Calculator" application window is focused and unshaded
    And the "Text Editor" application window is inactive and shaded by 45 percent
    When I disable the selected Hive extension
    Then no window actor retains a Shade Inactive Windows effect or transition
    When I enable the selected Hive extension
    Then the "Calculator" application window is focused and unshaded
    And the "Text Editor" application window is inactive and shaded by 45 percent

  Scenario: Disabling during a real focus fade removes the running transition and effect
    Given Shell animations are forced for the Shade transition scenario
    When I focus the "Text Editor" application window for shading using keyboard input
    Then the "Text Editor" application window is focused and unshaded
    And the "Calculator" application window is inactive and shaded by 45 percent
    When I change the Shade Inactive Windows fade duration to 1000 milliseconds
    And I focus the "Calculator" application window for shading using keyboard input
    And I disable Shade Inactive Windows while the "Text Editor" window is transitioning
    Then no window actor retains a Shade Inactive Windows effect or transition

  Scenario: Overview clones of inactive windows are not shaded and the original effect returns when overview closes
    When I focus the "Text Editor" application window for shading using keyboard input
    Then the "Text Editor" application window is focused and unshaded
    And the "Calculator" application window is inactive and shaded by 45 percent
    And a screenshot records the "Calculator" window shaded by 45 percent
    When I open the Shell overview for the clone-paint scenario
    Then the Shell overview is visible and contains a real clone of the "Calculator" window
    And the "Calculator" overview clone renders without the shade-inactive-windows brightness effect
    And a screenshot records the "Calculator" clone un-shaded in the overview
    When I close the Shell overview for the clone-paint scenario
    Then the "Text Editor" application window is focused and unshaded
    And the "Calculator" application window is inactive and shaded by 45 percent
    And no overview group retains clone actors for "Calculator" or "Text Editor"
