#!/usr/bin/env bash
# Print every SELinux AVC record the e2e guest has logged, across all boots.
#
# Runs inside the guest as root (piped over SSH: `sudo bash -s < this`).
# The VM is disposable and fresh, so "all records" is exactly the
# qualification run, including any lifecycle reboot. Records reach
# different sinks depending on whether auditd runs, so read all of them;
# scripts/selinux_qualify.py de-duplicates by audit serial.
set -uo pipefail

if command -v ausearch >/dev/null 2>&1 && [[ -s /var/log/audit/audit.log ]]; then
  ausearch -m AVC,USER_AVC --raw 2>/dev/null || true
fi
# Without auditd, kernel AVCs land in the journal via kmsg and userspace
# USER_AVCs (dbus-broker, systemd) via syslog/audit transports. Read every
# boot the journal kept; `-k` would limit this to the current boot.
journalctl --no-pager -o cat 2>/dev/null | grep -F 'avc:' || true
