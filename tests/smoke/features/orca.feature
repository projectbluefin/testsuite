@orca @accessibility @smoke_suite
Feature: Orca screen reader
  Verify the Orca screen reader stack is installed, the screen-reader
  gsettings toggle starts and stops Orca, and speech-dispatcher responds.

  @orca @binary @a11y
  Scenario: Orca and speech-dispatcher binaries are installed
    * Run command on VM: "command -v orca && command -v speech-dispatcher"
    * VM command return code is "0"
    * VM command output contains "/orca"
    * VM command output contains "/speech-dispatcher"

  @orca @a11y @bus
  Scenario: AT-SPI accessibility bus name is registered
    * Run command on VM: "busctl --user list | grep -q org.a11y.Bus"
    * VM command return code is "0"

  @orca @a11y @screen_reader @retry
  Scenario: Screen reader toggle starts and stops Orca
    * Screen reader enabled state toggles Orca on and off

  @orca @speech @retry
  Scenario: Speech Dispatcher responds to a module list request
    * Run command on VM: "spd-say -O"
    * VM command return code is "0"
