@common @bluefin
Feature: Bluefin common desktop entry validation
  Checks common-layer desktop integration artifacts over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: Sample of installed desktop files passes validation
    * Run SSH command: "find /usr/share/applications -name '*.desktop' | head -20 | xargs desktop-file-validate 2>&1 | grep -i '^[^:]*: error:' | wc -l | tr -d '[:space:]'"
    * SSH command output "is" "0"

  # projectbluefin/common ships these launchers in /usr/share/applications.
  Scenario: Common desktop launchers are present and valid
    * Run SSH command: "cd /usr/share/applications && desktop-file-validate bluefin-help.desktop discourse.desktop documentation.desktop system-update.desktop noop.desktop"
    * SSH command return code is "0"

  Scenario: GNOME Files application desktop entry is present
    * Run SSH command: "test -f /usr/share/applications/org.gnome.Nautilus.desktop"
    * SSH command return code is "0"

  Scenario: GNOME Settings application desktop entry is present
    * Run SSH command: "test -f /usr/share/applications/org.gnome.Settings.desktop"
    * SSH command return code is "0"

  Scenario: HTML MIME type has a default handler registered
    * Run SSH command: "xdg-mime query default text/html 2>/dev/null || grep -r 'text/html' /usr/share/applications/*.desktop | grep -c 'MimeType' | grep -v '^0$'"
    * SSH command return code is "0"

  Scenario: PDF MIME type has a default handler registered
    * Run SSH command: "xdg-mime query default application/pdf 2>/dev/null || grep -rl 'application/pdf' /usr/share/applications/*.desktop | wc -l | grep -v '^0$'"
    * SSH command return code is "0"

  Scenario: XDG icon theme directories are present
    * Run SSH command: "test -d /usr/share/icons/hicolor && test -d /usr/share/pixmaps"
    * SSH command return code is "0"

  Scenario: Installed desktop applications count is reasonable
    * Run SSH command: "cnt=$(find /usr/share/applications -name '*.desktop' | wc -l); [ $cnt -ge 10 ] && echo ok || echo fail"
    * SSH command output "is" "ok"
