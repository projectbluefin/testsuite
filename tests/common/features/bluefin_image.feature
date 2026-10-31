@common @bluefin
Feature: Bluefin shipping image contracts
  Validates files and defaults shipped by projectbluefin/bluefin (and the
  common bluefin overlay it consumes) on the booted VM.
  The fedora_bluefin_only tag marks contracts built only by projectbluefin/bluefin
  build_files (00-image-info.sh, 05-override-install.sh, 17-cleanup.sh,
  04-install-kernel-akmods.py) or bluefin-only system_files. It runs only on the
  bluefin and bluefin-nvidia images; Bluefin LTS, Utah, and Dakota build elsewhere.
  Step arguments use bare inner double quotes; Gherkin does not unescape backslashes.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # bluefin build_files/base/00-image-info.sh
  @fedora_bluefin_only
  Scenario: image-info.json identifies a signed projectbluefin Bluefin image
    * Run SSH command: ". /usr/lib/os-release; jq -e --arg n "$IMAGE_ID" '(.["image-name"] == $n) and ($n | startswith("bluefin")) and (.["image-vendor"] == "projectbluefin") and (.["image-ref"] == "ostree-image-signed:docker://ghcr.io/projectbluefin/" + $n) and (.["image-flavor"] == (if ($n | test("nvidia")) then "nvidia" else "main" end)) and (.["fedora-version"] | test("^[0-9]+$"))' /usr/share/ublue-os/image-info.json"
    * SSH command return code is "0"

  @fedora_bluefin_only
  Scenario: os-release carries Bluefin identity and variant
    * Run SSH command: ". /usr/lib/os-release && test "$ID" = bluefin && test "$NAME" = Bluefin && test "$VERSION_CODENAME" = Deinonychus && test "$ID_LIKE" = fedora && test "$VARIANT_ID" = "$IMAGE_ID" && test "${VARIANT_ID%-nvidia}" = bluefin && echo ok"
    * SSH command output "is" "ok"

  # bluefin + utah system_files/shared/etc/rpm-ostreed.conf
  Scenario: rpm-ostreed stages automatic updates
    * Run SSH command: "grep -x 'AutomaticUpdatePolicy=stage' /etc/rpm-ostreed.conf"
    * SSH command return code is "0"

  # bluefin 17-cleanup.sh: uupd replaces the legacy rpm-ostree updater
  @fedora_bluefin_only
  Scenario: Legacy rpm-ostreed automatic timer is not enabled
    * Run SSH command: "systemctl is-enabled rpm-ostreed-automatic.timer"
    * SSH command output is not "enabled" and not "enabled-runtime"

  # bluefin system_files/shared/usr/lib/systemd/system/fstrim.service.d/workaround-no-root-trim.conf
  @fedora_bluefin_only
  Scenario: fstrim drop-in skips unsupported filesystems
    * Run SSH command: "systemctl show -p ExecStart --value fstrim.service"
    * SSH command output contains "--listed-in /proc/self/mountinfo --verbose --quiet-unsupported"

  # bluefin 05-override-install.sh; firewalld.service is masked by the e2e harness,
  # so only the shipped configuration is asserted. firewalld.conf is not readable
  # by the test user on the booted VM, so it is read through passwordless sudo.
  @fedora_bluefin_only
  Scenario: firewalld ships the pinned Fedora Workstation defaults
    * Run SSH command: "sudo -n grep -xc -e 'DefaultZone=FedoraWorkstation' -e 'IPv6_rpfilter=loose' /etc/firewalld/firewalld.conf"
    * SSH command output stripped "is" "2"
    * Run SSH command: "sha256sum /usr/lib/firewalld/zones/FedoraWorkstation.xml | cut -d' ' -f1"
    * SSH command output stripped "is" "ceb2a036759ae52b623e2d50f2d6056e698ff6ce0763cfd76ef3f6a259b1a14e"

  @fedora_bluefin_only
  Scenario: Offline Bluefin documentation is a PDF
    * Run SSH command: "head -c 5 /usr/share/doc/bluefin/bluefin.pdf"
    * SSH command output "is" "%PDF-"

  # bluefin 05-override-install.sh links noto-cjk to google-noto-sans-cjk-fonts.
  # Product defect at bluefin@sha256:460d3a74: Fedora 44 ships
  # google-noto-sans-cjk-vf-fonts, so the alias is dangling.
  @fedora_bluefin_only
  Scenario: CJK font alias resolves to Noto Sans CJK
    * Run SSH command: "test -d /usr/share/fonts/noto-cjk/"
    * SSH command return code is "0"

  @fedora_bluefin_only
  Scenario: chsh and lchsh are not shipped
    * Run SSH command: "test ! -e /usr/bin/chsh && test ! -e /usr/bin/lchsh"
    * SSH command return code is "0"

  # bluefin 04-install-kernel-akmods.py install_v4l2loopback; utah scripts/install-v4l2loopback.sh
  Scenario: v4l2loopback module is installed for the booted kernel
    * Run SSH command: "/usr/sbin/modinfo -k $(uname -r) -F name v4l2loopback"
    * SSH command output stripped "is" "v4l2loopback"

  # bluefin 04-install-kernel-akmods.py configure_nvidia writes kargs only on nvidia flavors.
  @fedora_bluefin_only
  Scenario: NVIDIA kernel arguments ship exactly on the nvidia flavor
    * Run SSH command: "f=/usr/lib/bootc/kargs.d/00-nvidia.toml; flavor=$(jq -r '.["image-flavor"]' /usr/share/ublue-os/image-info.json); case $flavor in nvidia) grep -F nvidia-drm.modeset=1 $f && grep -F modprobe.blacklist=nouveau $f && grep -F initcall_blacklist=simpledrm_platform_driver_init $f && ! ls /usr/share/vulkan/icd.d/nouveau_icd.* ;; main) test ! -e $f ;; *) false ;; esac"
    * SSH command return code is "0"

  # custom-command-list menu as shipped in the image under test (Bluefin and Utah ship
  # 04-bluefin-custom-command-menu, LTS 05-uranium-custom-command-menu; rows below are
  # the values all three share).
  @requires_custom_command_list
  Scenario Outline: custom-command-list menu entry <key> is the shipped command
    * Run SSH command: "dconf read /org/gnome/shell/extensions/custom-command-list/<key>"
    * SSH command output stripped "is" "<value>"

    Examples:
      | key        | value                                                                           |
      | command6   | ('Bazaar App Store', '/usr/bin/flatpak run io.github.kolunmi.Bazaar', '', true) |
      | command8   | ('Terminal', 'xdg-terminal-exec', '', true)                                     |
      | command11  | ('Ask Bluefin', 'xdg-open https://ask.projectbluefin.io', '', true)             |

    # Values in the Bluefin image (bluefin@sha256:460d3a74); Utah and LTS ship different entries.
    @fedora_bluefin_only
    Examples: Bluefin-only entries
      | key        | value                                                                                    |
      | command7   | ('Extensions', '/usr/bin/flatpak run com.mattjakeman.ExtensionManager', '', true)        |
      | command10  | ('Documentation', 'flatpak run org.gnome.Papers /usr/share/doc/bluefin/bluefin.pdf', '', true) |

  # Checks the executable of every non-separator entry in the effective menu, so each
  # image is held to its own menu file. Product defect at bluefin@sha256:460d3a74 and
  # utah@sha256:a0baa947: command3 launches /usr/bin/missioncenter-helper, which neither
  # image ships. The final test fails if dconf returned no commands at all.
  @requires_custom_command_list
  Scenario: custom-command-list menu commands resolve on the image
    * Run SSH command: "n=0; for i in $(seq 1 11); do c=$(dconf read /org/gnome/shell/extensions/custom-command-list/command$i | awk -F"'" '{print $4}' | cut -d' ' -f1); if [ -n "$c" ]; then n=$((n+1)); command -v "$c" >/dev/null || echo missing:$c; fi; done; test $n -gt 0"
    * SSH command return code is "0"
    * SSH command output does not contain "missing:"

  # common system_files/bluefin/etc/xdg/mimeapps.list (consumed by Bluefin, Utah, and LTS)
  Scenario Outline: <mime> opens with <app> by default
    * Run SSH command: "grep -x '<mime>=<app>' /etc/xdg/mimeapps.list"
    * SSH command return code is "0"

    Examples:
      | mime                        | app                                 |
      | application/pdf             | org.gnome.Papers.desktop            |
      | application/vnd.flatpak.ref | io.github.kolunmi.Bazaar.desktop    |
      | image/png                   | org.gnome.Loupe.desktop             |
      | image/jpeg                  | org.gnome.Loupe.desktop             |
      | video/mp4                   | org.gnome.Showtime.desktop          |
      | video/webm                  | org.gnome.Showtime.desktop          |
