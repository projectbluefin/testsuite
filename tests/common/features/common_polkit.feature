@common @bluefin
Feature: Polkit rules presence
  Verifies polkitd is running and compiled every shipped rule file.
  Polkit rules control privilege escalation; missing rules hang first-login.
  The privileged-setup policy/rule contract lives in common_core_contracts.feature.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: pkcheck is available
    * Run SSH command: "pkcheck --version"
    * SSH command return code is "0"

  Scenario: polkit daemon is running
    * Run SSH command: "systemctl is-active polkit.service"
    * SSH command return code is "0"
    * Last command output contains "active"

  # polkitd logs "Error compiling script <file>" / "Error evaluating ..." for a
  # rule file it cannot load, and "Finished loading, compiling and executing
  # N rules" once every file is in.
  Scenario: polkitd loaded every rule file without errors
    * Run SSH command: "systemctl is-active polkit.service >/dev/null && sudo -n journalctl -b -u polkit.service --no-pager -o cat"
    * SSH command return code is "0"
    * SSH command output contains "Finished loading, compiling and executing"
    * SSH command output does not contain "Error compiling script"
    * SSH command output does not contain "Error evaluating"
