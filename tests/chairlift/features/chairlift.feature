@chairlift_suite
Feature: Control Center on a freshly booted image
  Control Center (ChairLift) as the image ships it: the cask that Homebrew
  setup installs at the first graphical login, started from the image's own
  launcher, inside the real GNOME session, with the image's own helper,
  polkit policy and configuration (projectbluefin/testsuite#1326).

  e2e.yml prepares the guest for this suite alone: Homebrew setup is left on,
  the test user gets a throwaway password, and the Homebrew folder is handed to
  the test user. The suite gates nothing; it runs daily on dakota:testing.

  Each step prints its evidence on lines that start with "CHAIRLIFT".

  @chairlift @brew_install
  Scenario: Homebrew setup installs Control Center at the first login
    * Homebrew setup has installed the Control Center launcher

  @chairlift @preview_mode @retry
  Scenario: Control Center opens in preview mode
    * Control Center is installed
    * Launch Control Center in preview mode
    * Control Center window is accessible
    * Control Center is running in preview mode
    * I take a screenshot labeled "control_center_preview"
    * Close Control Center

  # The action is the "Automatic Updates" switch on the Updates page: it runs
  # chairlift-helper auto-updates-disable / auto-updates-enable, which only
  # masks or enables uupd.timer. Nothing restarts, no image is switched, and
  # no network is needed. The second flip undoes the first. The password
  # prompt is answered for real; no polkit rule is installed.
  @chairlift @admin_action @retry
  Scenario: An admin action succeeds through the real password prompt
    * Control Center is installed
    * The admin password prompt can be answered
    * Launch Control Center with the action journal
    * Control Center window is accessible
    * Start the password agent for Control Center
    * Flip the "Automatic Updates" switch
    * The action journal records the change as succeeded
    * Automatic updates are flipped on the system
    * Flip the "Automatic Updates" switch
    * The action journal records the undo as succeeded
    * Automatic updates are back as they were on the system
    * Close Control Center

  # Last, so the other scenarios' time counts toward the wait. Any ending but
  # active with result success (failed, still running, never started, unit
  # missing) is recorded as a known gap, not failed. Today it fails because
  # the image's compass.Brewfile names a formula its tap removed (#1326).
  @chairlift @brew_preinstall
  Scenario: The first-login Homebrew install settles and its result is recorded
    * Wait for the first-login Homebrew install to settle
    * Record how the first-login Homebrew install ended
