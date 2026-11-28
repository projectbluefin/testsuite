@chairlift_suite
Feature: Control Center on a freshly booted image (spike, not for merge)
  Phase 0 of projectbluefin/testsuite#1326. Three scenarios, in order, each
  answering one open question from a real run. The answers are printed on
  lines that start with "CHAIRLIFT-SPIKE Q1", "Q2" and "Q3".

  Control Center (ChairLift) is a Homebrew cask that brew-preinstall.service
  installs at the first graphical login. e2e.yml leaves brew-setup.service
  unmasked and gives the test user a throwaway password for this suite only.

  @chairlift @spike_q1 @brew_install
  Scenario: Homebrew setup installs Control Center
    * Homebrew setup has installed the Control Center launcher

  @chairlift @spike_q2 @preview_mode
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
  # no network is needed. The second flip undoes the first.
  @chairlift @spike_q3 @admin_action
  Scenario: An admin action succeeds through the password prompt
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
