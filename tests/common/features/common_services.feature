@common @bluefin
Feature: Bluefin common systemd service health
  Validates high-risk custom Bluefin systemd services over SSH.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # Utah and Dakota delete rechunker-group-fix; an absent unit still reports
  # Result=success, so require it loaded.
  @fedora_bluefin_only
  Scenario: rechunker-group-fix service completed successfully
    * Run SSH command: "systemctl show rechunker-group-fix.service -p LoadState -p Result"
    * SSH command return code is "0"
    * SSH command output contains "LoadState=loaded"
    * SSH command output contains "Result=success"

  # hookrunner.sh runs every hook with plain `bash "$script"`, so the unit's
  # Result only reflects the last hook. Each hook that is not hardware-gated
  # records its version in libsetup's $HOME/.local/share/ublue/setup_versioning.json
  # (root's HOME for the system unit), so the recorded version must equal the
  # one the installed hook declares. A hook whose version-script guard fails
  # exits 0 without running, which is exactly what Result=success hides.
  Scenario: ublue-system-setup service completed successfully
    * Run SSH command: "systemctl show ublue-system-setup.service -p LoadState -p Result"
    * SSH command return code is "0"
    * SSH command output contains "LoadState=loaded"
    * SSH command output contains "Result=success"
    * Run SSH command: "v=$(grep -oE '^version-script(-commit)? framework system [0-9]+' /usr/share/ublue-os/system-setup.hooks.d/10-framework.sh | tail -1 | awk '{print $4}'); r=$(sudo -n jq -r .version.system.framework /root/.local/share/ublue/setup_versioning.json); echo shipped=$v recorded=$r; test ${#v} -gt 0 && test $v = $r && echo framework-committed"
    * SSH command output contains "framework-committed"

  Scenario: ublue-user-setup user service completed successfully
    * Run SSH command: "systemctl --user show ublue-user-setup.service -p LoadState -p Result"
    * SSH command return code is "0"
    * SSH command output contains "LoadState=loaded"
    * SSH command output contains "Result=success"
    * Run SSH command: "for h in 10-theming:theming 20-dynamic-wallpaper:dynamic-wallpaper; do f=/usr/share/ublue-os/user-setup.hooks.d/${h%%:*}.sh; n=${h#*:}; v=$(grep -oE "^version-script(-commit)? $n user [0-9]+" $f | tail -1 | awk '{print $4}'); r=$(jq -r --arg n $n '.version.user[$n]' ~/.local/share/ublue/setup_versioning.json); test ${#v} -gt 0 && test $v = $r && echo $n=committed || echo $n=shipped:$v:recorded:$r; done | paste -sd,"
    * SSH command output stripped "is" "theming=committed,dynamic-wallpaper=committed"

  # Pending: flatpak-preinstall.service is masked in e2e.yml, so it never runs in CI.
  @pending
  Scenario: flatpak-preinstall installed required applications
    * Run SSH command: "systemctl show flatpak-preinstall.service --property=ActiveState --value"
    * SSH command return code is "0"
    * SSH command output stripped "is" "active"
    * Run SSH command: "flatpak list --app --columns=application"
    * SSH command output contains "org.mozilla.firefox"
    * SSH command output contains "com.raggesilver.BlackBox"

  # Pending: flatpak-preinstall.service is masked in e2e.yml and /var/lib/flatpak is
  # never seeded, so no remotes exist to check.
  @pending
  Scenario: flatpak remotes are flathub only
    * Run SSH command: "systemctl show flatpak-nuke-fedora.service --property=ActiveState --value"
    * SSH command return code is "0"
    * SSH command output stripped "is" "active"
    * Run SSH command: "flatpak remotes --columns=name"
    * SSH command output contains "flathub"
    * SSH command output does not contain "fedora"

  Scenario: dconf database is compiled
    * Run SSH command: "systemctl show dconf-update.service --property=Result --value"
    * SSH command return code is "0"
    * SSH command output stripped "is" "success"
    * Run SSH command: "dconf dump /"
    * SSH command output is not empty

  @pending
  Scenario: bootc unified storage service completed successfully
    * Run SSH command: "systemctl show bootc-unified-storage.service --property=Result --value"
    * SSH command return code is "0"
