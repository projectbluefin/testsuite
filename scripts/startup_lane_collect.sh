#!/usr/bin/env bash
# Collect startup-lane evidence inside the guest (testsuite#1025).
#
# Runs in the VM as the SSH test user, piped over SSH:
#   ssh ... "SYSTEM_UNITS='a.service b.service' USER_UNITS='c.timer' \
#     PRODUCES='/x /y' CHECKS='flatpak' bash -s" < scripts/startup_lane_collect.sh
#
# Prints "@@ <section> [arg]" headers, each followed by that section's raw
# output. scripts/startup_lane.py parses and judges it; this script only reads
# state and never changes it.
set -u

PROPS=Id,LoadState,ActiveState,SubState,Result,ConditionResult,ConditionTimestampMonotonic,ExecMainStatus,NRestarts,UnitFileState

echo "@@ is-system-running"
systemctl is-system-running 2>&1

if [[ -n "${SYSTEM_UNITS:-}" ]]; then
  echo "@@ system-units"
  # shellcheck disable=SC2086
  systemctl show --no-pager -p "${PROPS}" ${SYSTEM_UNITS} 2>&1
fi

if [[ -n "${USER_UNITS:-}" ]]; then
  echo "@@ user-units"
  # shellcheck disable=SC2086
  systemctl --user show --no-pager -p "${PROPS}" ${USER_UNITS} 2>&1
fi

echo "@@ paths"
for path in ${PRODUCES:-}; do
  if [[ -e "${path}" ]]; then echo "yes ${path}"; else echo "no ${path}"; fi
done

if [[ " ${CHECKS:-} " == *" flatpak "* ]]; then
  # /etc drop-ins override /usr ones with the same file name (flatpak-preinstall(5)).
  for dir in /usr/share/flatpak/preinstall.d /etc/flatpak/preinstall.d; do
    for f in "${dir}"/*.preinstall; do
      [[ -f "${f}" ]] || continue
      echo "@@ preinstall-file ${f}"
      cat "${f}"
    done
  done

  echo "@@ remotes-declared"
  for dir in /usr/share/flatpak/remotes.d /etc/flatpak/remotes.d; do
    for f in "${dir}"/*.flatpakrepo; do
      [[ -f "${f}" ]] && basename "${f}" .flatpakrepo
    done
  done

  echo "@@ remotes"
  flatpak remotes --system --columns=name 2>&1

  echo "@@ installed"
  flatpak list --system --columns=application,branch,origin 2>&1

  # Shipped permission overrides are tmpfiles.d symlinks into the system
  # override directory, e.g.
  #   L /var/lib/flatpak/overrides/<app> - - - - /usr/share/.../<app>
  echo "@@ override-links"
  overrides=$(cat /usr/lib/tmpfiles.d/*.conf /etc/tmpfiles.d/*.conf 2>/dev/null \
    | awk '$1 ~ /^L/ && $2 ~ "^/var/lib/flatpak/overrides/" {print $2, $7}')
  while read -r link target; do
    [[ -n "${link}" ]] || continue
    echo "${link} ${target} $(readlink -f "${link}" 2>/dev/null || true)"
  done <<< "${overrides}"
  while read -r link target; do
    [[ -n "${link}" ]] || continue
    app=$(basename "${link}")
    echo "@@ override-file ${app}"
    cat "${target}" 2>&1
    echo "@@ permissions ${app}"
    flatpak info --system --show-permissions "${app}" 2>&1
  done <<< "${overrides}"
fi
