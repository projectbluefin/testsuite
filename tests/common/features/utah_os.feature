@common @utah_only
Feature: Utah OS contract
  Utah-only runtime checks verified against projectbluefin/utah 527c5aff and
  ghcr.io/projectbluefin/utah@sha256:a0baa947. Flavor hardware (NVIDIA, OGC
  kernel) is out of scope here; these hold on every flavor.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: os-release identifies Bluefin built on Hummingbird with the utah variant
    * Run SSH command: ". /usr/lib/os-release && echo $NAME/$ID/$VARIANT_ID/$IMAGE_ID/$VERSION_CODENAME"
    * SSH command output stripped "is" "Bluefin/hummingbird/utah/utah/Utahraptor"

  Scenario: image-info names the utah image and a published flavor
    * Run SSH command: "jq -r '[.["image-name"], .["image-vendor"], .["base-image-name"]] | join("/")' /usr/share/ublue-os/image-info.json"
    * SSH command output stripped "is" "utah/projectbluefin/hummingbird"
    * Run SSH command: "jq -r '.["image-flavor"]' /usr/share/ublue-os/image-info.json | grep -Ex 'main|nvidia|gaming|nvidia-gaming'"
    * SSH command return code is "0"

  Scenario: zram swap is active
    * Run SSH command: "swapon --show=NAME --noheadings"
    * SSH command output contains "zram0"

  Scenario: Lid close uses suspend-then-hibernate
    * Run SSH command: "systemd-analyze cat-config systemd/logind.conf | grep -E '^HandleLidSwitch(ExternalPower|Docked)?=' | sort"
    * SSH command output contains "HandleLidSwitch=suspend-then-hibernate"
    * SSH command output contains "HandleLidSwitchDocked=suspend-then-hibernate"
    * SSH command output contains "HandleLidSwitchExternalPower=suspend-then-hibernate"

  Scenario: authselect enables silent lastlog and fingerprint
    * Run SSH command: "authselect current"
    * SSH command return code is "0"
    * SSH command output contains "with-silent-lastlog"
    * SSH command output contains "with-fingerprint"

  Scenario: systemd-resolved runs without PrivateTmp
    * Run SSH command: "systemctl is-active systemd-resolved.service"
    * SSH command output stripped "is" "active"
    * Run SSH command: "systemctl show -p PrivateTmp --value systemd-resolved.service"
    * SSH command output stripped "is" "no"

  Scenario: tuna-os Flatpak remote is configured system-wide
    * Run SSH command: "flatpak remotes --system --columns=name,url"
    * SSH command output contains "tuna-os"
    * SSH command output contains "oci+https://tunaos.org/flatpak"

  Scenario: Bazaar and Ghostty are declared for Flatpak preinstall
    * Run SSH command: "cat /usr/share/flatpak/preinstall.d/bazaar.preinstall /usr/share/flatpak/preinstall.d/ghostty.preinstall"
    * SSH command output contains "[Flatpak Preinstall io.github.kolunmi.Bazaar]"
    * SSH command output contains "CollectionID=org.flathub.Stable"
    * SSH command output contains "[Flatpak Preinstall com.mitchellh.ghostty]"
    * SSH command output contains "CollectionID=org.tunaos"

  # The e2e harness writes /etc/projectbluefin/countme/disabled into every
  # deployment, so the shipped default is read from the ostree /usr/etc copy.
  Scenario: CountMe timer is enabled and the image ships no opt-out marker
    * Run SSH command: "systemctl is-enabled projectbluefin-countme.timer && test -x /usr/libexec/projectbluefin-countme && test -d /usr/etc && test ! -e /usr/etc/projectbluefin/countme/disabled && echo COUNTME_READY"
    * SSH command output contains "COUNTME_READY"

  Scenario: CountMe start limit tolerates harness bursts
    * Run SSH command: "systemctl show -p StartLimitBurst -p StartLimitIntervalUSec projectbluefin-countme.service"
    * SSH command output contains "StartLimitBurst=20"
    * SSH command output contains "StartLimitIntervalUSec=2min"

  Scenario: CountMe honors the opt-out marker without running the client
    * CountMe service start is skipped while the opt-out marker exists

  # Known product defect: Utah's `ujust report` routes through
  # /usr/local/libexec/utah-image-repo, but /usr/local is /var/usrlocal on a
  # bootc deployment, so the shim never ships (absent from sha256:a0baa947).
  Scenario: ujust report routes bug reports to projectbluefin/utah
    * Run SSH command: "ujust --show report"
    * SSH command output contains "/usr/local/libexec/utah-image-repo"
    * Run SSH command: "/usr/local/libexec/utah-image-repo --default projectbluefin/common utah"
    * SSH command return code is "0"
    * SSH command output stripped "is" "projectbluefin/utah"

  Scenario: Ghostty user setup hook links its Flatpak config to the host config
    * Run SSH command: "jq -r '.version.user["30-ghostty"]' ~/.local/share/ublue/setup_versioning.json"
    * SSH command output stripped "is" "1"
    * Run SSH command: "[ $(readlink -f ~/.var/app/com.mitchellh.ghostty/config/ghostty) = $(readlink -f ~/.config/ghostty) ] && grep -h '^theme' ~/.config/ghostty/config ~/.config/ghostty/config.ghostty 2>/dev/null"
    * SSH command output contains "theme ="
