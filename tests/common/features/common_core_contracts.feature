@common
Feature: projectbluefin/common core shipping contracts
  Runtime checks for contracts shipped by projectbluefin/common e33665e2
  (system_files/shared): the privileged-setup polkit policy and wheel-only
  rule, the sudoers.d/001-bootc grant, the uupd timers/drop-ins/config, and
  /usr/libexec/ublue-booted-image. Runs on every common consumer, Dakota
  included; scenarios that only one consumer ships carry an image tag.

  Background:
    * Bluefin VM is booted and reachable over SSH

  # org.ublue.privileged.user.setup.policy: allow_any/inactive/active = no.
  Scenario: privileged user setup action denies by default
    * Run SSH command: "pkaction --verbose --action-id org.ublue.policykit.privileged.user.setup | awk '/implicit/ {print $NF}' | paste -sd,"
    * SSH command return code is "0"
    * SSH command output stripped "is" "no,no,no"

  # A non-wheel subject (a nobody-owned process) gets no grant from
  # 20-privileged-user-setup.rules: the setup action falls to its "no" default
  # (pkcheck rc 1) and pkexec of the helper falls to the exec action's
  # auth_admin default (rc 2: authentication required, no agent).
  Scenario: non-wheel users are not authorized for privileged user setup
    * Run SSH command: "sudo -n sh -c 'setpriv --reuid=nobody --regid=nobody --clear-groups sleep 30 & p=$!; sleep 1; pkcheck --action-id org.ublue.policykit.privileged.user.setup --process $p; a=$?; pkcheck --action-id org.freedesktop.policykit.exec --detail program /usr/bin/ublue-privileged-setup --process $p; b=$?; kill $p; echo setup=$a exec=$b'"
    * SSH command return code is "0"
    * SSH command output contains "setup=1 exec=2"

  # The CI user is in wheel (e2e.yml), so the rule must grant both the setup
  # action and pkexec of /usr/bin/ublue-privileged-setup. polkit only lets
  # uid 0 pass --detail, so root asks about the SSH shell ($$).
  Scenario: wheel users are authorized for privileged user setup
    * Run SSH command: "id -nG"
    * SSH command output contains "wheel"
    * Run SSH command: "sudo -n pkcheck --action-id org.ublue.policykit.privileged.user.setup --process $$; a=$?; sudo -n pkcheck --action-id org.freedesktop.policykit.exec --detail program /usr/bin/ublue-privileged-setup --process $$; echo setup=$a exec=$?"
    * SSH command output contains "setup=0 exec=0"

  # etc/sudoers.d/001-bootc lets wheel run `bootc upgrade` without a password.
  Scenario: sudoers grants wheel passwordless bootc upgrade
    * Run SSH command: "sudo -n cat /etc/sudoers.d/001-bootc"
    * SSH command return code is "0"
    * SSH command output stripped "is" "%wheel ALL=(ALL) NOPASSWD: /usr/bin/bootc upgrade"
    * Run SSH command: "sudo -n -l"
    * SSH command return code is "0"
    * SSH command output contains "NOPASSWD: /usr/bin/bootc upgrade"

  # Common's uupd.timer ships only on Fedora Bluefin; Utah, LTS and Dakota
  # replace it with their own (upstream-style) units.
  @fedora_bluefin_only
  Scenario: uupd timer runs on the common schedule
    * Run SSH command: "systemctl show -P TimersCalendar uupd.timer"
    * SSH command output contains "OnCalendar=*-*-* 00,06,12,18:00:00"
    * Run SSH command: "systemctl show -p RandomizedDelayUSec -p Persistent uupd.timer"
    * SSH command output contains "RandomizedDelayUSec=10min"
    * SSH command output contains "Persistent=yes"

  # utah@527c5aff scripts/configure-services.sh installs upstream uupd v1.4.0 units.
  @utah_only
  Scenario: Utah uupd timer runs on the upstream schedule
    * Run SSH command: "systemctl show -P TimersCalendar uupd.timer"
    * SSH command output contains "OnCalendar=*-*-* 04:00:00"
    * Run SSH command: "systemctl show -p RandomizedDelayUSec -p Persistent uupd.timer"
    * SSH command output contains "RandomizedDelayUSec=15min"
    * SSH command output contains "Persistent=yes"

  # dakota@testing elements/bluefin/uupd.bst writes its own uupd.timer.
  @dakota_only
  Scenario: Dakota uupd timer runs on its shipped schedule
    * Run SSH command: "systemctl show -P TimersCalendar uupd.timer"
    * SSH command output contains "OnCalendar=*-*-* 04:00:00"
    * Run SSH command: "systemctl show -p RandomizedDelayUSec -p Persistent uupd.timer"
    * SSH command output contains "RandomizedDelayUSec=15min"
    * SSH command output contains "Persistent=yes"

  # uupd-resume.timer + 01-uupd.preset (enable uupd-resume.timer).
  Scenario: uupd resume timer re-runs updates after sleep
    * Run SSH command: "systemctl show -P TimersMonotonic uupd-resume.timer"
    * SSH command output contains "OnActiveUSec=20min"
    * Run SSH command: "systemctl show -P Unit uupd-resume.timer"
    * SSH command output stripped "is" "uupd.service"
    * Run SSH command: "systemctl is-enabled uupd-resume.timer"
    * SSH command output stripped "is" "enabled"

  # uupd.service.d/10-bluefin.conf, uupd-on-ac.service and
  # udev/rules.d/99-uupd-on-ac.rules: updates only on AC, at most once per 6h.
  Scenario: uupd runs only on AC power and the AC trigger is wired
    * Run SSH command: "systemctl show -P DropInPaths uupd.service"
    * SSH command output contains "/usr/lib/systemd/system/uupd.service.d/10-bluefin.conf"
    # Conditions is a(sbbsi) on the loaded unit: (type, trigger, negate, param, state).
    * Run SSH command: "for u in uupd uupd-on-ac; do p=$(busctl call org.freedesktop.systemd1 /org/freedesktop/systemd1 org.freedesktop.systemd1.Manager LoadUnit s $u.service | cut -d'"' -f2); echo $u=$(busctl get-property org.freedesktop.systemd1 $p org.freedesktop.systemd1.Unit Conditions | grep -o '"ConditionACPower" false false "true"' | wc -l); done | paste -sd,"
    * SSH command output stripped "is" "uupd=1,uupd-on-ac=1"
    * Run SSH command: "systemctl show -p StartLimitBurst -p StartLimitIntervalUSec uupd-on-ac.service"
    * SSH command output contains "StartLimitBurst=1"
    * SSH command output contains "StartLimitIntervalUSec=6h"
    * Run SSH command: "systemctl show -P ExecStart uupd-on-ac.service"
    * SSH command output contains "/usr/bin/systemctl start uupd.service"
    * Run SSH command: "udevadm verify /usr/lib/udev/rules.d/99-uupd-on-ac.rules"
    * SSH command return code is "0"

  # etc/uupd/config.json disables the distrobox module (Fedora Bluefin, Utah, LTS).
  @bluefin
  Scenario: uupd config disables the distrobox module
    * Run SSH command: "jq -c . /etc/uupd/config.json"
    * SSH command return code is "0"
    * SSH command output stripped "is" "{"modules":{"distrobox":{"disable":true}}}"

  # dakota@testing uupd.bst overwrites config.json with hardware checks and
  # disables distrobox on the uupd.service command line instead.
  @dakota_only
  Scenario: Dakota uupd disables distrobox and keeps hardware checks
    * Run SSH command: "systemctl show -P ExecStart uupd.service"
    * SSH command output contains "--disable-module-distrobox"
    * Run SSH command: "jq -c '.checks.hardware' /etc/uupd/config.json"
    * SSH command output stripped "is" "{"enable":true,"bat-min-percent":20,"cpu-max-percent":50,"mem-max-percent":90,"net-max-bytes":700000}"

  # usr/libexec/ublue-booted-image: the unprivileged reader must report the
  # ref bootc actually booted, and as name exactly that ref's repository
  # basename (digest, repository path and tag stripped here independently).
  Scenario: ublue-booted-image reports the booted bootc ref
    * Run SSH command: "b=$(sudo -n bootc status --json | jq -r .status.booted.image.image.image); r=$(/usr/libexec/ublue-booted-image ref); n=$(/usr/libexec/ublue-booted-image name); x=${b%%@*}; x=${x##*/}; x=${x%%:*}; echo booted=$b ref=$r name=$n expected-name=$x; test ${#x} -gt 0 && test $b != null && test "$r" = "$b" && test "$n" = "$x" && echo booted-image-match"
    * SSH command output contains "booted-image-match"
