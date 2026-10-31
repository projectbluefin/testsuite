@common @bluefin
Feature: Bluefin shipping image contracts
  Validates files and defaults shipped by projectbluefin/bluefin (and the
  common bluefin overlay it consumes) on the booted VM.
  The skip_utah tag marks contracts built only by projectbluefin/bluefin build_files
  (00-image-info.sh, 05-override-install.sh, 17-cleanup.sh, 04-install-kernel-akmods.py)
  or bluefin-only system_files; Utah builds its own image and does not run them.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # bluefin build_files/base/00-image-info.sh
  @skip_utah
  Scenario: image-info.json identifies a signed projectbluefin Bluefin image
    * Run SSH command: ". /usr/lib/os-release; jq -e --arg n \"$IMAGE_ID\" '.\"image-name\" == $n and (.\"image-name\" | startswith(\"bluefin\")) and .\"image-vendor\" == \"projectbluefin\" and .\"image-ref\" == \"ostree-image-signed:docker://ghcr.io/projectbluefin/\" + $n and .\"image-flavor\" == (if ($n | test(\"nvidia\")) then \"nvidia\" else \"main\" end) and (.\"fedora-version\" | test(\"^[0-9]+$\"))' /usr/share/ublue-os/image-info.json"
    * SSH command return code is "0"

  @skip_utah
  Scenario: os-release carries Bluefin identity and variant
    * Run SSH command: ". /usr/lib/os-release; echo \"$ID|$NAME|$VERSION_CODENAME|$ID_LIKE|$VARIANT_ID\" | grep -qEx 'bluefin\|Bluefin\|Deinonychus\|fedora\|bluefin(-nvidia)?' && [ \"$VARIANT_ID\" = \"$IMAGE_ID\" ] && echo ok"
    * SSH command output "is" "ok"

  # bluefin + utah system_files/shared/etc/rpm-ostreed.conf
  Scenario: rpm-ostreed stages automatic updates
    * Run SSH command: "grep -x 'AutomaticUpdatePolicy=stage' /etc/rpm-ostreed.conf"
    * SSH command return code is "0"

  # bluefin 17-cleanup.sh: uupd replaces the legacy rpm-ostree updater
  @skip_utah
  Scenario: Legacy rpm-ostreed automatic timer is not enabled
    * Run SSH command: "systemctl is-enabled rpm-ostreed-automatic.timer"
    * SSH command output is not "enabled" and not "enabled-runtime"

  # bluefin system_files/shared/usr/lib/systemd/system/fstrim.service.d/workaround-no-root-trim.conf
  @skip_utah
  Scenario: fstrim drop-in skips unsupported filesystems
    * Run SSH command: "systemctl show -p ExecStart --value fstrim.service"
    * SSH command output contains "--listed-in /proc/self/mountinfo --verbose --quiet-unsupported"

  # bluefin 05-override-install.sh; firewalld.service is masked by the e2e harness,
  # so only the shipped configuration is asserted.
  @skip_utah
  Scenario: firewalld ships the pinned Fedora Workstation defaults
    * Run SSH command: "grep -x 'DefaultZone=FedoraWorkstation' /etc/firewalld/firewalld.conf && grep -x 'IPv6_rpfilter=loose' /etc/firewalld/firewalld.conf && sha256sum /usr/lib/firewalld/zones/FedoraWorkstation.xml | cut -d' ' -f1"
    * SSH command return code is "0"
    * SSH command output contains "ceb2a036759ae52b623e2d50f2d6056e698ff6ce0763cfd76ef3f6a259b1a14e"

  @skip_utah
  Scenario: Offline Bluefin documentation is a PDF
    * Run SSH command: "head -c 5 /usr/share/doc/bluefin/bluefin.pdf"
    * SSH command output "is" "%PDF-"

  @skip_utah
  Scenario: CJK font alias resolves to Noto Sans CJK
    * Run SSH command: "readlink /usr/share/fonts/noto-cjk && test -d /usr/share/fonts/noto-cjk/"
    * SSH command return code is "0"
    * SSH command output stripped "is" "/usr/share/fonts/google-noto-sans-cjk-fonts"

  @skip_utah
  Scenario: chsh and lchsh are not shipped
    * Run SSH command: "test ! -e /usr/bin/chsh && test ! -e /usr/bin/lchsh"
    * SSH command return code is "0"

  # bluefin 04-install-kernel-akmods.py install_v4l2loopback; utah scripts/install-v4l2loopback.sh
  Scenario: v4l2loopback module is installed for the booted kernel
    * Run SSH command: "modinfo -k \"$(uname -r)\" -F name v4l2loopback"
    * SSH command output stripped "is" "v4l2loopback"

  # bluefin 04-install-kernel-akmods.py configure_nvidia writes kargs only on nvidia flavors.
  @skip_utah
  Scenario: NVIDIA kernel arguments ship exactly on the nvidia flavor
    * Run SSH command: "f=/usr/lib/bootc/kargs.d/00-nvidia.toml; if [ \"$(jq -r '.\"image-flavor\"' /usr/share/ublue-os/image-info.json)\" = nvidia ]; then grep -F 'nvidia-drm.modeset=1' $f && grep -F 'modprobe.blacklist=nouveau' $f && grep -F 'initcall_blacklist=simpledrm_platform_driver_init' $f && ! ls /usr/share/vulkan/icd.d/nouveau_icd.* 2>/dev/null; else test ! -e $f; fi"
    * SSH command return code is "0"

  # bluefin + utah system_files/shared/etc/dconf/db/distro.d/04-bluefin-custom-command-menu
  @requires_custom_command_list
  Scenario Outline: custom-command-list menu entry <key> is the shipped command
    * Run SSH command: "dconf read /org/gnome/shell/extensions/custom-command-list/<key>"
    * SSH command output stripped "is" "<value>"

    Examples:
      | key        | value                                                                                |
      | command3   | ('System Monitor', '/usr/bin/missioncenter-helper', '', true)                        |
      | command6   | ('Bazaar App Store', '/usr/bin/flatpak run io.github.kolunmi.Bazaar', '', true)      |
      | command7   | ('Extensions', 'flatpak run com.mattjakeman.ExtensionManager', '', true)             |
      | command8   | ('Terminal', 'xdg-terminal-exec', '', true)                                          |
      | command10  | ('Documentation', 'xdg-open https://docs.projectbluefin.io/', '', true)              |
      | command11  | ('Ask Bluefin', 'xdg-open https://ask.projectbluefin.io', '', true)                  |

  @requires_custom_command_list
  Scenario: custom-command-list menu commands resolve on the image
    * Run SSH command: "for c in /usr/bin/missioncenter-helper /usr/bin/flatpak xdg-terminal-exec xdg-open gnome-control-center; do command -v $c >/dev/null || echo missing:$c; done"
    * SSH command return code is "0"
    * SSH command output does not contain "missing:"

  # common system_files/bluefin/etc/xdg/mimeapps.list (consumed by Bluefin and Utah)
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
