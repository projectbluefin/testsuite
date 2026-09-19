@native_app @smoke_suite
Feature: GNOME Online Accounts smoke tests
  Validates the GNOME Online Accounts settings panel opens, exposes a
  non-empty provider list, and that the GOA daemon is available.

  @settings @online_accounts @launch @sla_15s @retry
  Scenario: Online Accounts panel is accessible
    * Launch Settings via command
    * Settings window is accessible
    * Navigate to Settings panel "Online Accounts"
    * Settings panel "Online Accounts" is visible

  @settings @online_accounts @providers @sla_15s
  Scenario: Online Accounts provider list is non-empty
    * Launch Settings via command
    * Settings window is accessible
    * Navigate to Settings panel "Online Accounts"
    * Settings panel "Online Accounts" is visible
    * Online Accounts provider list is non-empty

  @settings @online_accounts @daemon @sla_10s
  Scenario: goa-daemon is running
    * Navigate to Settings panel "Online Accounts"
    * Run and save command output: "sleep 3; pgrep -x goa-daemon && echo running"
    * Last command output "contains" "running"
