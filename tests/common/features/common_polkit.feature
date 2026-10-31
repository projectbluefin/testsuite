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

  # polkit.service runs `polkitd --log-level=notice`. polkit 127 logs
  # "Error compiling script <file>" / "Error evaluating admin rules" at ERROR
  # (shown), but "Finished loading, compiling and executing N rules" at INFO
  # (suppressed). So: the journal must hold this boot's polkitd start banner and
  # no rule error, and a shipped JS rule must actually evaluate: pkexec of
  # ublue-privileged-setup defaults to auth_admin and is granted to the wheel
  # CI user only by 20-privileged-user-setup.rules.
  Scenario: polkitd loaded every rule file without errors
    * Run SSH command: "systemctl is-active polkit.service >/dev/null && sudo -n journalctl -b -u polkit.service --no-pager -o cat"
    * SSH command return code is "0"
    * SSH command output contains "Started polkitd version"
    * SSH command output does not contain "Error compiling script"
    * SSH command output does not contain "Error evaluating"
    * Run SSH command: "id -nG"
    * SSH command output contains "wheel"
    * Run SSH command: "sudo -n pkcheck --action-id org.freedesktop.policykit.exec --detail program /usr/bin/ublue-privileged-setup --process $$"
    * SSH command return code is "0"
