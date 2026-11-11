#!/usr/bin/env bash
# Trigger one deliberate SELinux denial in the e2e guest and report how it went.
#
# Runs inside the guest as root (piped over SSH: `sudo bash -s < this`).
# Prints `key=value` lines only; scripts/selinux_qualify.py (`canary
# --diagnostics`) reads them to tell "the canary could not run" apart from
# "the canary ran but its denial was not collected" (#1141).
#
# The canary starts a transient unit in a confined domain that may not use
# /usr/bin/cat (bin_t) as its entrypoint, so execve fails with EACCES and
# systemd reports status 203/EXEC. Candidate domains are tried in order; a
# domain the loaded policy lacks fails earlier (229/SELINUX_CONTEXT) and the
# next one is tried, so the canary does not depend on one policy module.
set -uo pipefail

CANDIDATES=(httpd_t sshd_t getty_t syslogd_t chronyd_t)
EXIT_EXEC=203

one_line() { tr '\n' ' ' | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'; }

canary_type=none
canary_rc=none
canary_status=none
canary_stderr=
for type in "${CANDIDATES[@]}"; do
  out=$(timeout 60 systemd-run --wait --collect \
    -p StandardOutput=null -p StandardError=null \
    -p "SELinuxContext=system_u:system_r:${type}:s0" \
    /usr/bin/cat /etc/shadow 2>&1)
  rc=$?
  status=$(sed -nE 's/.*status=([0-9]+).*/\1/p' <<<"${out}" | tail -n 1)
  echo "attempt_${type}=rc=${rc} status=${status:-none}"
  canary_type=${type}
  canary_rc=${rc}
  canary_status=${status:-none}
  canary_stderr=$(one_line <<<"${out}")
  # 203/EXEC: the policy blocked execve, which is the denial we want.
  [[ "${status}" == "${EXIT_EXEC}" || ( -z "${status}" && "${rc}" == "${EXIT_EXEC}" ) ]] && break
done
echo "canary_type=${canary_type}"
echo "canary_rc=${canary_rc}"
echo "canary_status=${canary_status}"
echo "canary_stderr=${canary_stderr}"

# Let auditd/journald write the record before the collector reads it.
sleep 3

echo "collector_context=$(id -Z 2>/dev/null || echo unknown)"
echo "cmdline=$(one_line </proc/cmdline)"
echo "getenforce=$(getenforce 2>/dev/null || echo unavailable)"
if command -v seinfo >/dev/null 2>&1; then
  echo "seinfo_httpd_t=$(seinfo -t httpd_t 2>&1 | one_line)"
  echo "seinfo_canary_type=$(seinfo -t "${canary_type}" 2>&1 | one_line)"
else
  echo "seinfo_httpd_t=unavailable (no seinfo)"
fi
if command -v sesearch >/dev/null 2>&1 && [[ "${canary_type}" != none ]]; then
  echo "sesearch_dontaudit=$(sesearch --dontaudit -s "${canary_type}" -t bin_t -c file 2>&1 | one_line)"
fi
if [[ -s /var/log/audit/audit.log ]]; then
  echo "audit_log=present ($(grep -cF 'avc:' /var/log/audit/audit.log) avc lines)"
elif [[ -e /var/log/audit/audit.log ]]; then
  echo "audit_log=empty"
else
  echo "audit_log=missing"
fi
echo "auditd=$(systemctl is-active auditd.service 2>/dev/null || true)"
if command -v auditctl >/dev/null 2>&1; then
  echo "auditctl_status=$(auditctl -s 2>&1 | one_line)"
fi
echo "journal_kernel_avc=$(journalctl -k --no-pager 2>/dev/null | grep -c avc)"
echo "journal_avc=$(journalctl --no-pager -o cat 2>/dev/null | grep -cF 'avc:')"
echo "dmesg_avc=$(dmesg 2>/dev/null | grep -cF 'avc:')"
