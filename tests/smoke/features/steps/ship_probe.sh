#!/bin/bash
# Throwaway read-only probe: records what the booted image really ships.
# Spike only (branch spike/ship-probe), never merged.
#
# Output format, for a parser:
#   "=== <section>"   starts a section
#   "$ <command>"     the command that runs next
#   "[exit N]"        its exit status
#   "[missing] <tool>" the tool is not on PATH; its commands were skipped
#
# Read-only: no installs, no service start/stop, no ujust recipe but --list.
# No `set -e`: a failing command is recorded, never fatal.

CMD_TIMEOUT=${SHIP_PROBE_CMD_TIMEOUT:-180}

# Same session environment the suite's own steps use.
if [ -f /tmp/session.env ]; then
  # shellcheck disable=SC1091
  . /tmp/session.env 2>/dev/null || true
fi
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
: "${DBUS_SESSION_BUS_ADDRESS:=unix:path=${XDG_RUNTIME_DIR}/bus}"
export XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS

SSH_PATH=$PATH
# shellcheck disable=SC2016 # $PATH expands in the login shell
LOGIN_PATH=$(env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL=/bin/bash \
  bash -lc 'printf %s "$PATH"' </dev/null 2>/dev/null)
if [ -n "$LOGIN_PATH" ]; then
  PATH="$LOGIN_PATH:$SSH_PATH"
fi
export PATH

if command -v timeout >/dev/null 2>&1; then
  HAVE_TIMEOUT=1
else
  HAVE_TIMEOUT=0
fi

section() {
  echo
  echo "=== $1"
}

# run '<command string>': echo it, run it in bash, record the exit status.
run() {
  echo "\$ $1"
  if [ "$HAVE_TIMEOUT" = 1 ]; then
    timeout "$CMD_TIMEOUT" bash -c "$1" </dev/null 2>&1
  else
    bash -c "$1" </dev/null 2>&1
  fi
  echo "[exit $?]"
}

# need <tool>: true when present, otherwise print "[missing] <tool>".
need() {
  if command -v "$1" >/dev/null 2>&1; then
    return 0
  fi
  echo "[missing] $1"
  return 1
}

# run_if <tool> '<command string>'
run_if() {
  if need "$1"; then
    run "$2"
  fi
}

# run_if_path <path> '<command string>': skip quietly-but-visibly when absent.
run_if_path() {
  if [ -e "$1" ]; then
    run "$2"
  else
    echo "\$ $2"
    echo "[absent] $1"
    echo "[exit 2]"
  fi
}

DESKTOP_DIRS=(
  /usr/share/applications
  /var/lib/flatpak/exports/share/applications
  "$HOME/.local/share/flatpak/exports/share/applications"
  "$HOME/.local/share/applications"
  /home/linuxbrew/.linuxbrew/share/applications
)

echo "ship-probe v1 $(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"

# ── identity ────────────────────────────────────────────────────────────────
section identity
echo "PATH (ssh)=$SSH_PATH"
echo "PATH (login)=$LOGIN_PATH"
echo "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
run_if_path /usr/share/ublue-os/image-info.json 'cat /usr/share/ublue-os/image-info.json'
run 'cat /etc/os-release'
run 'uname -r'
run 'cat /proc/cmdline'
run_if bootc 'sudo -n bootc status'
run_if rpm-ostree 'rpm-ostree status'
run 'uptime'
run 'id'
run 'hostnamectl 2>/dev/null || true'

# ── harness ─────────────────────────────────────────────────────────────────
section harness
echo "# Things the e2e harness changed in this guest; discount them."
run 'systemctl list-unit-files --state=masked --no-pager --no-legend'
run 'systemctl --user list-unit-files --state=masked --no-pager --no-legend'
run "tr ' ' '\n' < /proc/cmdline | grep systemd.mask"
run "tr ' ' '\n' < /proc/cmdline | grep -E '^(systemd\.|selinux=|enforcing=)'"
run_if getenforce 'getenforce'
run 'ls -la /etc/systemd/system | grep -- "-> /dev/null"'
run_if_path /etc/gdm/custom.conf 'cat /etc/gdm/custom.conf'
run 'sudo -n ls -la /etc/sudoers.d'
run 'ls -la /etc/ssh/sshd_config.d'
run_if_path /etc/ssh/sshd_config.d/00-ci-auth.conf 'cat /etc/ssh/sshd_config.d/00-ci-auth.conf'
run_if_path /etc/tmpfiles.d/ci-user.conf 'cat /etc/tmpfiles.d/ci-user.conf'
run_if_path /etc/dconf/db/local.d/00-ci-testing 'cat /etc/dconf/db/local.d/00-ci-testing'
run 'ls -la /etc/projectbluefin/countme 2>&1'
run 'getent passwd bluefin-test; getent group wheel'
run 'grep bluefin-test /etc/subuid /etc/subgid'
run 'ls -la ~/.config/environment.d && cat ~/.config/environment.d/*'
run 'ls -la ~/.local/bin ~/.local/libexec ~/.local/share/dbus-1/services 2>&1'
run_if_path /tmp/session.env 'cat /tmp/session.env'
run_if podman 'podman images --format "{{.Repository}}:{{.Tag}} {{.ID}}"'
run_if flatpak 'flatpak remotes --system --columns=name,url'

# ── packages ────────────────────────────────────────────────────────────────
section packages
run_if rpm 'rpm -qa --qf "%{NAME}\t%{VERSION}-%{RELEASE}\n" | sort'

# ── binaries ────────────────────────────────────────────────────────────────
section binaries
run 'ls -1 /usr/bin | sort'
run 'ls -1 /usr/libexec | sort'
for tool in gnome-shell gnome-software gnome-control-center gnome-initial-setup \
  gdm sshd firewalld firewall-cmd zsh fish bash ptyxis ghostty nautilus \
  gnome-text-editor gnome-calculator gnome-disks baobab papers loupe showtime \
  firefox code podman docker distrobox toolbox virt-manager qemu-system-x86_64 \
  libvirtd tailscale ujust just brew fastfetch bluefin-cli chairlift \
  chairlift-helper missioncenter-helper nethogs uupd bootc fwupdmgr \
  xdg-terminal-exec kanata sudo sudo-rs flatpak ibus gamemoderun; do
  echo "\$ command -v $tool"
  if command -v "$tool" 2>/dev/null; then
    echo "[exit 0]"
  else
    echo "[missing] $tool"
    echo "[exit 1]"
  fi
done

# ── desktop-files ───────────────────────────────────────────────────────────
section desktop-files
for d in "${DESKTOP_DIRS[@]}"; do
  run_if_path "$d" "ls -1 '$d' | grep '\\.desktop\$' | sort"
done

# ── flatpak ─────────────────────────────────────────────────────────────────
section flatpak
if need flatpak; then
  run 'flatpak remotes --show-details'
  run 'flatpak list --system --columns=application,branch,origin,installation'
  run 'flatpak list --user --columns=application,branch,origin,installation'
fi
for d in /usr/share/flatpak/preinstall.d /etc/flatpak/preinstall.d; do
  if [ -d "$d" ]; then
    run "ls -la '$d'"
    for f in "$d"/*; do
      [ -f "$f" ] && run "cat '$f'"
    done
  else
    run_if_path "$d" "ls -la '$d'"
  fi
done
run "systemctl list-unit-files --no-legend --no-pager 'flatpak-preinstall*'"
run "systemctl --user list-unit-files --no-legend --no-pager 'flatpak-preinstall*'"
for u in $(systemctl list-unit-files --no-legend --no-pager 'flatpak-preinstall*' 2>/dev/null | awk '{print $1}'); do
  run "systemctl status --no-pager -n 20 '$u'"
done
for u in $(systemctl --user list-unit-files --no-legend --no-pager 'flatpak-preinstall*' 2>/dev/null | awk '{print $1}'); do
  run "systemctl --user status --no-pager -n 20 '$u'"
done

# ── extensions ──────────────────────────────────────────────────────────────
section extensions
run 'ls -1 /usr/share/gnome-shell/extensions'
run 'ls -1 ~/.local/share/gnome-shell/extensions'
if need gnome-extensions; then
  run 'gnome-extensions list --details'
  run 'gnome-extensions list --enabled'
fi
if need gsettings; then
  for k in enabled-extensions disabled-extensions disable-user-extensions \
    disable-extension-version-validation favorite-apps; do
    run "gsettings get org.gnome.shell $k"
  done
fi

# ── favourites-resolve ──────────────────────────────────────────────────────
section favourites-resolve
if command -v gsettings >/dev/null 2>&1; then
  FAVS=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null | grep -o "'[^']*'" | tr -d "'")
  echo "\$ gsettings get org.gnome.shell favorite-apps (resolved per id)"
  for id in $FAVS; do
    where=MISSING
    for d in "${DESKTOP_DIRS[@]}"; do
      if [ -e "$d/$id" ]; then
        where=$d
        break
      fi
    done
    printf '%s\t%s\n' "$id" "$where"
  done
  echo "[exit 0]"
else
  echo "[missing] gsettings"
fi

# ── settings ────────────────────────────────────────────────────────────────
section settings
run_if gsettings 'gsettings list-recursively'
run_if dconf 'dconf dump /'
run 'sudo -n ls -R /etc/dconf/db'
run 'ls -R /etc/dconf/profile 2>&1; cat /etc/dconf/profile/* 2>&1'

# ── mime ────────────────────────────────────────────────────────────────────
section mime
if need xdg-mime; then
  for m in text/html x-scheme-handler/https x-scheme-handler/mailto image/png \
    image/jpeg video/mp4 audio/mpeg application/pdf text/plain inode/directory \
    application/zip; do
    run "xdg-mime query default $m"
  done
fi
for f in /usr/share/applications/mimeapps.list /etc/xdg/mimeapps.list \
  "$HOME/.config/mimeapps.list"; do
  run_if_path "$f" "cat '$f'"
done

# ── terminal ────────────────────────────────────────────────────────────────
section terminal
run "find /etc/xdg /usr/share -maxdepth 3 -name '*xdg-terminals.list' 2>/dev/null"
while IFS= read -r f; do
  run "cat '$f'"
done < <(find /etc/xdg /usr/share -maxdepth 3 -name '*xdg-terminals.list' 2>/dev/null)
run_if_path /usr/share/xdg-terminals 'ls -1 /usr/share/xdg-terminals'
if need xdg-terminal-exec; then
  XTE=$(command -v xdg-terminal-exec)
  # Never launch a terminal: only ask for the id when the script supports it.
  if grep -q -- '--print-id' "$XTE" 2>/dev/null; then
    run 'xdg-terminal-exec --print-id'
  else
    echo "\$ xdg-terminal-exec --print-id"
    echo "[skipped] $XTE has no --print-id option"
    echo "[exit 2]"
  fi
fi

# ── units ───────────────────────────────────────────────────────────────────
section units
run 'systemctl list-unit-files --no-legend --no-pager'
run 'systemctl --user list-unit-files --no-legend --no-pager'
run 'systemctl list-timers --all --no-pager'
run 'systemctl --user list-timers --all --no-pager'
run 'systemctl --failed --no-pager'
run 'systemctl --user --failed --no-pager'
run 'systemctl cat uupd.timer uupd.service'
run_if_path /etc/uupd/config.json 'cat /etc/uupd/config.json'
for u in gdm sshd firewalld tailscaled uupd.timer projectbluefin-countme.timer \
  flatpak-preinstall.service bootc-fetch-apply-updates.timer fwupd-refresh.timer \
  libvirtd.socket docker.socket podman.socket qemu-guest-agent brew-setup.service; do
  run "systemctl is-enabled $u"
  run "systemctl is-active $u"
done
for u in brew-preinstall.service compass.service bazaar.service \
  ublue-user-setup.service syncthing.service; do
  run "systemctl --user is-enabled $u"
  run "systemctl --user is-active $u"
done

# ── tooling ─────────────────────────────────────────────────────────────────
section tooling
run_if ujust 'ujust --list'
run 'ls -R /usr/share/ublue-os'
run 'ls -la /home/linuxbrew /home/linuxbrew/.linuxbrew/bin'
run 'ls -1 /etc/profile.d'
for d in /usr/share/ublue-os/user-setup.hooks.d \
  /usr/share/ublue-os/privileged-setup.hooks.d \
  /usr/share/ublue-os/system-setup.hooks.d; do
  run_if_path "$d" "ls -la '$d'"
done
run 'ls -la ~/.local/share/ublue ~/.config/ublue 2>/dev/null'

# ── containers ──────────────────────────────────────────────────────────────
section containers
if need podman; then
  run 'podman --version'
  run 'podman info --format "{{.Host.Security.Rootless}}"'
fi
run_if distrobox 'distrobox --version'
run_if docker 'docker --version'
run_if_path /etc/containers/policy.json 'cat /etc/containers/policy.json'
run_if_path /etc/containers/registries.d 'ls -la /etc/containers/registries.d'

# ── security ────────────────────────────────────────────────────────────────
section security
run_if getenforce 'getenforce'
run_if aa-status 'aa-status --enabled; echo $?'
if need firewall-cmd; then
  run 'firewall-cmd --state'
  run 'firewall-cmd --get-default-zone'
fi
run 'sudo --version | head -2'
run 'readlink -f /usr/bin/sudo'
run 'readlink -f /usr/bin/ls'
run 'sysctl kernel.kexec_load_disabled'
run_if mokutil 'mokutil --sb-state'
run 'sudo -n ls -1 /usr/share/polkit-1/rules.d'
run 'sudo -n ls -1 /etc/polkit-1/rules.d'
run 'test -e /sys/block/zram0; echo $?'
run 'cat /proc/swaps'

# ── wallpaper-fonts ─────────────────────────────────────────────────────────
section wallpaper-fonts
if need gsettings; then
  run 'gsettings get org.gnome.desktop.background picture-uri'
  run 'gsettings get org.gnome.desktop.background picture-uri-dark'
fi
for d in /usr/share/backgrounds /usr/share/backgrounds/bluefin; do
  run_if_path "$d" "ls -la '$d'"
done
if need gsettings; then
  for k in font-name document-font-name monospace-font-name color-scheme accent-color; do
    run "gsettings get org.gnome.desktop.interface $k"
  done
fi
run_if fc-list 'fc-list : family | sort -u | head -80'

# ── hardware ────────────────────────────────────────────────────────────────
section hardware
run "ls /usr/lib/udev/rules.d | grep -i -E 'bluefin|ublue|framework|uaccess|usb'"
run_if fwupdmgr 'fwupdmgr --version'
run 'ls /usr/lib/modules-load.d /etc/modules-load.d'

section end
echo "ship-probe complete"
