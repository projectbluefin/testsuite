@common @bluefin
Feature: Bluefin common ujust recipes
  Validates non-destructive, non-interactive ujust recipes over SSH.
  Runs on Bluefin-family images (Bluefin, LTS, Utah); Dakota overrides the
  recipe set and is covered by its own dakota_ujust_* features.

  Background:
    * Bluefin VM is booted and reachable over SSH

  Scenario: ujust parses cleanly and ships the common recipe inventory
    # Strict parse: a just syntax error or shadowed import fails --summary or
    # prints to stderr. The names are the shared common recipe set.
    * Run SSH command: "err=$(ujust --summary 2>&1 >/dev/null) || { echo summary-failed; exit 1; }; [ -z $err ] || { echo stderr=$err; exit 1; }; out=$(ujust --summary); missing=; for r in bazaar-preview benchmark bios bios-info bluefin-apps bluefin-cli bluespeed changelogs check-idle-power-draw check-local-overrides check-sb-key clean-system cncf device-info devmode enroll-secure-boot-key install-ai-tools install-asus install-jetbrains-toolbox install-opentabletdriver install-system-flatpaks jetbrains-toolbox logs-last-boot logs-this-boot powerwash report setup-vms toggle-devmode toggle-testing toggle-tpm2 toggle-updates toggle-user-motd toggle-vms update; do printf '%s\n' $out | grep -qx -- $r || missing=$missing,$r; done; echo missing=$missing"
    * SSH command return code is "0"
    * SSH command output stripped "is" "missing="

  Scenario: ujust honors NO_COLOR in check-local-overrides
    # Plant one /etc-only file so the recipe has a line to colour, then remove it.
    * Run SSH command: "sudo touch /etc/ujust-nocolor-probe; trap 'sudo rm -f /etc/ujust-nocolor-probe' EXIT; f=$(mktemp); NO_COLOR=1 ujust check-local-overrides >$f; echo nocolor_esc=$(grep -c $'\x1b' $f) probe=$(grep -c ujust-nocolor-probe $f) color_esc=$(ujust check-local-overrides | grep -c $'\x1b' | sed 's/^[1-9][0-9]*$/present/'); rm -f $f"
    * SSH command output stripped "is" "nocolor_esc=0 probe=1 color_esc=present"

  Scenario: ujust logs-this-boot prints the current boot journal
    * Run SSH command: "ujust logs-this-boot"
    * SSH command return code is "0"
    * SSH command output is not empty

  Scenario: ujust bios-info prints firmware metadata
    # The labels are echoed even when dmidecode fails, so assert values.
    * Run SSH command: "set -o pipefail; ujust bios-info | grep -Ec '^(Version|Release Date): [^ ]'"
    * SSH command return code is "0"
    * SSH command output stripped "is" "2"

  Scenario: ujust toggle-updates drives both uupd timers and restores them
    # Shipping common update.just toggles uupd.timer and uupd-resume.timer
    # together; cancel must not change state. Original state is restored on exit.
    * Run SSH command: "E0=$(systemctl is-enabled uupd.timer); R0=$(systemctl is-enabled uupd-resume.timer); A0=$(systemctl is-active uupd.timer); AR0=$(systemctl is-active uupd-resume.timer); restore() { for u in uupd.timer:$E0:$A0 uupd-resume.timer:$R0:$AR0; do IFS=: read -r n e a <<< $u; if [ $e = enabled ]; then sudo systemctl enable -q $n; else sudo systemctl disable -q $n; fi; if [ $a = active ]; then sudo systemctl start $n; else sudo systemctl stop $n; fi; done; }; trap restore EXIT; ujust toggle-updates cancel </dev/null; c=$(systemctl is-enabled uupd.timer); d=$(ujust toggle-updates DISABLE </dev/null | tail -1 | tr ' ' _); dm=$(systemctl is-enabled uupd.timer uupd-resume.timer | paste -sd,); da=$(systemctl is-active uupd.timer); e=$(ujust toggle-updates enable </dev/null | tail -1 | tr ' ' _); em=$(systemctl is-enabled uupd.timer uupd-resume.timer | paste -sd,); ea=$(systemctl is-active uupd.timer); echo cancel_kept=$([ $c = $E0 ] && echo yes) disable=$d:$dm:$da enable=$e:$em:$ea; restore; trap - EXIT; echo restored=$([ $(systemctl is-enabled uupd.timer) = $E0 ] && [ $(systemctl is-enabled uupd-resume.timer) = $R0 ] && [ $(systemctl is-active uupd.timer) = $A0 ] && [ $(systemctl is-active uupd-resume.timer) = $AR0 ] && echo yes)"
    * SSH command return code is "0"
    * SSH command output contains "cancel_kept=yes disable=Updates_have_been_disabled:disabled,disabled:inactive enable=Updates_have_been_enabled:enabled,enabled:active"
    * SSH command output contains "restored=yes"

  Scenario: ujust toggle-testing refuses an unknown channel before switching
    * Run SSH command: "f=$(mktemp); echo '{"image-tag":"weird","image-ref":"ostree-image-signed:docker://ghcr.io/projectbluefin/bluefin"}' >$f; IMAGE_INFO_FILE=$f ujust toggle-testing </dev/null 2>&1; rc=$?; rm -f $f; exit $rc"
    * SSH command return code is "1"
    * SSH command output contains "Cannot toggle testing from channel 'weird'."

  Scenario: ujust report rejects an invalid --confirm target without posting
    * Run SSH command: "ujust report --confirm abc </dev/null 2>&1"
    * SSH command return code is "1"
    * SSH command output contains "Usage: ujust report"

  # Pending: glow is unavailable because brew-setup.service is masked in CI (#487).
  @pending
  Scenario: ujust changelogs renders release notes
    * Run SSH command: "command -v glow >/dev/null && ujust changelogs"
    * SSH command return code is "0"
    * SSH command output is not empty
