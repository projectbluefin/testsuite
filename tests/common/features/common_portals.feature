@common @bluefin
Feature: XDG desktop portal health
  The XDG desktop portal broker enables Flatpak sandbox permissions,
  file chooser dialogs, screenshot capture, and screen casting.
  All Flatpak apps depend on portals being active.

  Background:
    * Bluefin VM is booted and reachable over SSH

  @regression
  Scenario: graphical-session.target is active in the user session
    * Run SSH command: "systemctl --user is-active graphical-session.target"
    * SSH command return code is "0"

  @regression
  Scenario: xdg-desktop-portal did not fail due to missing session target
    * Run SSH command: "systemctl --user show xdg-desktop-portal.service --property=Result --value"
    * SSH command return code is "0"
    * SSH command output stripped "is" "success"

  Scenario: xdg-desktop-portal user service is active
    * Run SSH command: "systemctl --user is-active xdg-desktop-portal 2>/dev/null || systemctl --user status xdg-desktop-portal | grep -E 'active|running'"
    * SSH command return code is "0"

  Scenario: xdg-desktop-portal-gnome user service is active
    * Run SSH command: "systemctl --user is-active xdg-desktop-portal-gnome 2>/dev/null"
    * SSH command return code is "0"

  Scenario: xdg-desktop-portal D-Bus interface is reachable
    * Run SSH command: "gdbus introspect --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop 2>&1 | head -3"
    * SSH command return code is "0"
    * SSH command output contains "portal"

  Scenario: podman user socket is active
    * Run SSH command: "systemctl --user is-active podman.socket 2>/dev/null"
    * SSH command return code is "0"

  Scenario: podman info reports a working runtime
    * Run SSH command: "podman info --format '{{.Version.Version}}' 2>/dev/null"
    * SSH command return code is "0"
    * SSH command output is not empty
