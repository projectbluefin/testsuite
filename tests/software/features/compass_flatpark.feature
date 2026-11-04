@software_suite
Feature: FlatPark remote and the Compass Flatpak lifecycle
  common ships the FlatPark system remote (remotes.d/flatpark.flatpakrepo, with
  Filter=/usr/share/flatpak/flatpark.filter). ChairLift's incoming Compass
  switch installs org.tunaos.compass from it with
  `flatpak install -y --system flatpark org.tunaos.compass` and removes it
  without --delete-data. These scenarios drive that real path on the VM.
  Install needs network to dl.flatpark.org, github.com (extra-data) and a
  system remote serving org.freedesktop.Platform//26.08 (Flathub).

  The skip_bluefin tag marks scenarios that need the FlatPark remote: Bluefin's
  pinned common predates projectbluefin/common#1549, which added it. Drop the
  tag when Bluefin's common pin includes #1549.

  @software @flatpak_cli @flatpark @skip_bluefin
  Scenario: FlatPark system remote is configured with its shipped filter
    * Flatpak system remote "flatpark" uses filter "/usr/share/flatpak/flatpark.filter"

  @software @flatpak_cli @flatpark @compass @skip_bluefin
  Scenario: FlatPark lists Compass for this architecture
    * the VM is x86_64, the only arch FlatPark builds Compass for
    * Run SSH command: "flatpak remote-ls --system flatpark --app --columns=application | grep -qx org.tunaos.compass"
    * SSH command return code is "0"

  # common main (#1356) enables compass@tunaos.org in its Bluefin schema
  # override; Compass's ADR-0004 expects the image to bake the extension in,
  # because the Flatpak cannot install it. Images without that default skip.
  @software @flatpak_cli @compass
  Scenario: An image that enables the Compass Shell extension by default ships it
    * the image enables GNOME Shell extension "compass@tunaos.org" by default
    * Run SSH command: "grep -Eq '"uuid": *"compass@tunaos.org"' /usr/share/gnome-shell/extensions/compass@tunaos.org/metadata.json"
    * SSH command return code is "0"

  @software @flatpak_cli @flatpark @compass @skip_bluefin
  Scenario: Compass installs system-wide from FlatPark and uninstalls keeping user data
    * the VM is x86_64, the only arch FlatPark builds Compass for
    * Compass is absent now and removed again when the scenario ends
    # sudo -n: the SSH session has no polkit agent; the flatpak argv is ChairLift's.
    * Run long SSH command: "sudo -n flatpak install -y --system flatpark org.tunaos.compass"
    * SSH command return code is "0"
    * Flatpak system app "org.tunaos.compass" reports origin "flatpark", branch "stable" and arch "x86_64"
    # apply_extra unpacked the AppImage into /app/extra/compass.
    * Run SSH command: "test -x $(flatpak info --system --show-location org.tunaos.compass)/files/extra/compass/AppRun"
    * SSH command return code is "0"
    * Flatpak system app "org.tunaos.compass" permission "Session Bus Policy" sets "org.freedesktop.Flatpak" to "talk"
    * Flatpak system app "org.tunaos.compass" filesystem permissions include "host-os:ro"
    * Flatpak system app "org.tunaos.compass" has no home filesystem grant
    * Run SSH command: "grep -qx X-Flatpak=org.tunaos.compass /var/lib/flatpak/exports/share/applications/org.tunaos.compass.desktop"
    * SSH command return code is "0"
    * Run SSH command: "grep -qx X-Flatpak=org.tunaos.compass /var/lib/flatpak/exports/share/applications/org.tunaos.compass.UrlHandler.desktop && grep -q '^MimeType=.*x-scheme-handler/compass;' /var/lib/flatpak/exports/share/applications/org.tunaos.compass.UrlHandler.desktop"
    * SSH command return code is "0"
    * Run SSH command: "mkdir -p ~/.var/app/org.tunaos.compass/config/compass && echo testsuite > ~/.var/app/org.tunaos.compass/config/compass/testsuite-uninstall-marker"
    * SSH command return code is "0"
    * Run long SSH command: "sudo -n flatpak uninstall -y --system org.tunaos.compass"
    * SSH command return code is "0"
    * Run SSH command: "! flatpak info --system org.tunaos.compass >/dev/null 2>&1"
    * SSH command return code is "0"
    * Run SSH command: "cat ~/.var/app/org.tunaos.compass/config/compass/testsuite-uninstall-marker"
    * SSH command output "is" "testsuite"
