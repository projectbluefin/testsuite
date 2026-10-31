@common @dakota_only
Feature: Dakota OS shipping contracts
  Verifies Dakota-specific OS contracts from projectbluefin/dakota origin/testing
  (7da52839) on the booted VM: image identity, privilege model, polkit rules,
  memory/swap, home layout, composefs UDisks hiding, virtualization tooling, and
  launcher cleanup. Source map: docs/skills/test-authoring/suite-map/references/dakota-os.md.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # include/os-release.yml: ID, ID_LIKE, codename, NAME-first ordering guard.
  Scenario: os-release identifies Bluefin Dakota
    * Run SSH command: ". /usr/lib/os-release; echo id=$ID like=$ID_LIKE codename=$VERSION_CODENAME vendor=$IMAGE_VENDOR flavor=$IMAGE_FLAVOR"
    * SSH command return code is "0"
    * SSH command output contains "id=bluefin-dakota "
    * SSH command output contains "like=org.gnome.os "
    * SSH command output contains "codename=Dakotaraptor "
    * SSH command output contains "vendor=projectbluefin "
    * Run SSH command: "readlink -f /etc/os-release"
    * SSH command output stripped "is" "/usr/lib/os-release"
    # umotd/uwelcome take the first *NAME= line as the OS name.
    * Run SSH command: "grep -m1 -o '^[A-Z_]*NAME=' /usr/lib/os-release"
    * SSH command output stripped "is" "NAME="

  Scenario: os-release image name and signed ref match a published Dakota variant
    * Run SSH command: ". /usr/lib/os-release; case $IMAGE_NAME in dakota|dakota-nvidia|dakota-gaming|dakota-nvidia-gaming) echo name-ok;; esac; [ $IMAGE_REF = ostree-image-signed:docker://ghcr.io/projectbluefin/$IMAGE_NAME ] && echo ref-ok"
    * SSH command output contains "name-ok"
    * SSH command output contains "ref-ok"

  # files/firstboot/ublue-booted-image-sync records the real booted ref and
  # bind-mounts a corrected image-info.json over the baked "latest" copy.
  Scenario: ublue-booted-image records the bootc booted image ref
    * Run SSH command: "systemctl is-active ublue-booted-image.service"
    * SSH command output stripped "is" "active"
    * Run SSH command: "b=$(sudo bootc status --json | jq -r .status.booted.image.image.image); r=$(cat /run/ublue-os/booted-image); echo booted=$b; [ -n $b ] && [ $b = $r ] && echo booted-ref-match"
    * SSH command return code is "0"
    * SSH command output contains "booted-ref-match"

  Scenario: image-info.json reports the booted tag instead of the baked one
    # Mirror ublue-booted-image-sync: a digest ref has no tag, ref keeps the repo.
    * Run SSH command: "mountpoint -q /usr/share/ublue-os/image-info.json && echo bound; b=$(cat /run/ublue-os/booted-image); r=${b%@*}; n=${r##*/}; if [ $r != $b ]; then t=; else case $n in *:*) t=${n##*:}; r=${r%:*};; *) t=latest;; esac; fi; f=/usr/share/ublue-os/image-info.json; [ $(jq -r --arg k image-tag '.[$k]' $f)x = ${t}x ] && echo tag-match; jq -r --arg k image-ref '.[$k]' $f | grep -q -- ${r}$ && echo ref-match"
    * SSH command output contains "bound"
    * SSH command output contains "tag-match"
    * SSH command output contains "ref-match"

  # elements/bluefin/sudo-rs.bst + sudo-linuxbrew-path.bst.
  Scenario: sudo-rs owns sudo and appends Homebrew to secure_path
    * Run SSH command: "sudo --version | head -1; stat -c %a /usr/bin/sudo"
    * SSH command output contains "sudo-rs"
    * SSH command output contains "4755"
    * Run SSH command: "readlink /usr/bin/sudoedit"
    * SSH command output stripped "is" "sudo"
    # Source chmods 0440; the published image carries 0600 for every
    # sudoers.d file. Either is valid for sudo-rs: root-owned, no group/other write.
    * Run SSH command: "find /etc/sudoers.d/linuxbrew -maxdepth 0 -user root ! -perm /022 -printf secure"
    * SSH command output stripped "is" "secure"
    * Run SSH command: "sudo -n sh -c 'echo $PATH'"
    * SSH command return code is "0"
    * SSH command output stripped "is" "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin"

  Scenario: sudo PAM stack delegates every phase to system-auth
    * Run SSH command: "grep -cE '^(auth|account|password|session)[[:space:]]+include[[:space:]]+system-auth' /etc/pam.d/sudo"
    * SSH command output stripped "is" "4"

  # elements/bluefin/uupd.bst ships /etc/polkit-1/rules.d/uupd.rules; polkitd
  # evaluates it, so pkcheck proves the rule parses and grants exactly uupd units.
  # polkit only lets uid 0 pass --detail, so root asks about the SSH shell ($$).
  Scenario: uupd polkit rule lets users manage only uupd units
    * Run SSH command: "sudo pkcheck --action-id org.freedesktop.systemd1.manage-units --process $$ --detail unit uupd.service"
    * SSH command return code is "0"
    * Run SSH command: "sudo pkcheck --action-id org.freedesktop.systemd1.manage-units --process $$ --detail unit uupd-manual.service"
    * SSH command return code is "0"
    * Run SSH command: "sudo pkcheck --action-id org.freedesktop.systemd1.manage-units --process $$ --detail unit sshd.service; echo rc=$?"
    * SSH command output contains "rc="
    * SSH command output does not contain "rc=0"
    * SSH command output does not contain "rc=127"

  # files/polkit/org.freedesktop.NetworkManager.rules (wheel + local only).
  Scenario: NetworkManager wheel polkit rule grants only local wheel users
    # Evaluate the shipped rule in gjs with a stub polkit: local wheel -> yes,
    # remote wheel -> no decision (falls through to the action default).
    * Run SSH command: "f=/usr/share/polkit-1/rules.d/org.freedesktop.NetworkManager.rules; t=$(mktemp --suffix=.js); { echo "var polkit={Result:{YES:'yes'},addRule:function(f){var a={id:'org.freedesktop.NetworkManager.settings.modify.system'};var s={local:true,isInGroup:function(g){return g==='wheel'}};print(f(a,s));s.local=false;print(f(a,s));}};"; cat $f; } > $t; gjs $t > $t.out; rc=$?; tr '\n' ' ' < $t.out; rm -f $t $t.out; exit $rc"
    * SSH command return code is "0"
    * SSH command output stripped "is" "yes undefined"
    * Run SSH command: "pkaction --action-id org.freedesktop.NetworkManager.settings.modify.system"
    * SSH command return code is "0"
    # Non-local wheel subject must not get the passwordless grant.
    * Run SSH command: "pkcheck --action-id org.freedesktop.NetworkManager.settings.modify.system --process $$"
    * Last command exits with non-zero status

  # elements/bluefin/tailscale-setup.bst.
  Scenario: Tailscale authorize action requires admin and its helper ships
    * Run SSH command: "pkaction --verbose --action-id org.projectbluefin.dakota.tailscale.authorize"
    * SSH command return code is "0"
    * SSH command output contains "/usr/libexec/dakota-tailscale-authorize"
    * Run SSH command: "pkaction --verbose --action-id org.projectbluefin.dakota.tailscale.authorize | awk '/implicit active:/{print $3}'"
    * SSH command output stripped "is" "auth_admin"
    * Run SSH command: "test -x /usr/libexec/dakota-tailscale-authorize && test -x /usr/libexec/dakota-tailscale-setup && echo helpers-ok"
    * SSH command output stripped "is" "helpers-ok"

  # elements/bluefin/chairlift.bst.
  Scenario: ChairLift privileged helper is registered with polkit
    * Run SSH command: "pkaction --verbose --action-id io.projectbluefin.chairlift.ublue.channel-switch"
    * SSH command return code is "0"
    * SSH command output contains "/usr/bin/chairlift-helper"
    * Run SSH command: "pkaction --verbose --action-id io.projectbluefin.chairlift.ublue.channel-switch | awk '/implicit active:/{print $3}'"
    * SSH command output stripped "is" "auth_admin_keep"
    * Run SSH command: "test -x /usr/bin/chairlift-helper && echo helper-ok"
    * SSH command output stripped "is" "helper-ok"

  # elements/bluefin/zswap-config.bst; kargs.d is applied by bootc on
  # switch/upgrade, so assert the shipped kargs and the live sysctls.
  Scenario: zswap kernel arguments and swap sysctls are configured
    * Run SSH command: "cat /usr/lib/bootc/kargs.d/20-zswap.toml"
    * SSH command output contains "zswap.enabled=1"
    * SSH command output contains "zswap.compressor=zstd"
    * SSH command output contains "zswap.max_pool_percent=20"
    * SSH command output contains "zswap.shrinker_enabled=1"
    * Run SSH command: "sysctl -n vm.swappiness vm.watermark_scale_factor vm.watermark_boost_factor | tr '\n' ' '"
    * SSH command output stripped "is" "100 200 0"

  # elements/bluefin/swapfile.bst: zram disabled, disk swapfile fronted by zswap.
  Scenario: zram is disabled and the swapfile follows its init contract
    * Run SSH command: "{ grep -c '^\[zram' /usr/lib/systemd/zram-generator.conf; swapon --show=NAME --noheadings | grep -c zram; } | tr '\n' ' '"
    * SSH command output stripped "is" "0 0"
    # /var/swap is 0700 root, so probe it through sudo.
    * Run SSH command: "systemctl show -p Result --value bluefin-swapfile-init.service; if sudo test -e /var/swap/swapfile; then swapon --show=NAME --noheadings | grep -qx /var/swap/swapfile && echo swapfile-state=active || echo swapfile-state=inactive; else sudo journalctl -b -o cat -u bluefin-swapfile-init.service | grep -q skipping && echo swapfile-state=skipped || echo swapfile-state=missing; fi"
    * SSH command output contains "success"
    * SSH command output contains "swapfile-state="
    * SSH command output does not contain "swapfile-state=inactive"
    * SSH command output does not contain "swapfile-state=missing"

  # elements/bluefin/bindmounts.bst.
  Scenario: home, root and snap are bind mounts of their var locations
    * Run SSH command: "for p in home:/var/home root:/var/roothome snap:/var/lib/snapd/snap; do t=/${p%%:*}; s=${p#*:}; systemctl is-active ${t#/}.mount >/dev/null && [ $(stat -c %d:%i $t) = $(sudo stat -c %d:%i $s) ] && echo $t-bound; done"
    * SSH command output contains "/home-bound"
    * SSH command output contains "/root-bound"
    * SSH command output contains "/snap-bound"

  # elements/bluefin/migrate-var-home-passwd.bst. The e2e harness creates
  # bluefin-test with the legacy /var/home field (pre-#1117 layout), so the
  # migration must rewrite it.
  Scenario: legacy /var/home passwd entries are migrated to /home
    * Run SSH command: "{ systemctl is-enabled bluefin-migrate-var-home-passwd.service; systemctl show -p Result --value bluefin-migrate-var-home-passwd.service; } | tr '\n' ' '"
    * SSH command output stripped "is" "enabled success"
    * Run SSH command: "getent passwd $(id -un) | cut -d: -f6"
    * SSH command output stripped "is" "/home/bluefin-test"
    * Run SSH command: "grep -cE ':(/var/home/|/var/roothome)(:|$)' /etc/passwd"
    * SSH command output stripped "is" "0"

  # files/udev/90-hide-composefs-loop.rules. The e2e lane boots with the legacy
  # ostree bind mount (no composefs loop), so attach a real erofs loop device
  # and detach it again.
  Scenario: erofs loop devices are hidden from UDisks
    * Run SSH command: "udevadm verify /usr/lib/udev/rules.d/90-hide-composefs-loop.rules"
    * SSH command return code is "0"
    * Run SSH command: "d=$(mktemp -d /var/tmp/erofs.XXXXXX); l=; mkdir $d/src && echo x > $d/src/f && mkfs.erofs $d/img $d/src >/dev/null 2>&1 && l=$(sudo losetup -f --show $d/img) && sudo udevadm settle && udevadm info -q property $l | grep -x -e ID_FS_TYPE=erofs -e UDISKS_IGNORE=1 | sort | tr '\n' ' '; test -z $l || sudo losetup -d $l; rm -rf $d"
    * SSH command output stripped "is" "ID_FS_TYPE=erofs UDISKS_IGNORE=1"

  # elements/bluefin/virtualization.bst, libvirt.bst, files/libvirt/80-libvirt.preset.
  Scenario: libvirt and virtiofsd tooling ship with daemons preset-disabled
    * Run SSH command: "virsh --version && /usr/libexec/virtiofsd --version && qemu-system-x86_64 --version | head -1"
    * SSH command return code is "0"
    * SSH command output contains "virtiofsd"
    * SSH command output contains "QEMU emulator"
    * Run SSH command: "getent group libvirt kvm | cut -d: -f1 | tr '\n' ' '"
    * SSH command output stripped "is" "libvirt kvm"
    * Run SSH command: "systemctl is-enabled libvirtd.socket virtqemud.socket libvirt-guests.service | tr '\n' ' '"
    * SSH command output stripped "is" "disabled disabled disabled"

  # elements/bluefin/common.bst (#1829) removes upstream duplicates of the
  # system-update, discourse and documentation launchers.
  Scenario: duplicate common launchers are removed
    * Run SSH command: "ls /usr/share/applications/system-update.desktop /usr/share/applications/discourse.desktop /usr/share/applications/documentation.desktop 2>/dev/null | wc -l"
    * SSH command output stripped "is" "0"
