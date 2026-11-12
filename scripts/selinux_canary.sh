#!/usr/bin/env bash
# Trigger one deliberate SELinux denial in the e2e guest and report how it went.
#
# Runs inside the guest as root (piped over SSH: `sudo bash -s < this`).
# Prints `key=value` lines only (`canary_output_<domain>` keeps every attempt's
# systemd-run output, `canary_stderr` the last one); scripts/selinux_qualify.py (`canary
# --diagnostics`) reads them to tell "the canary could not run" apart from
# "the canary ran but its denial was not collected" (#1141).
#
# The canary starts a transient unit in a confined domain that may not use
# /usr/bin/cat (bin_t) as its entrypoint, so execve fails with EACCES and
# systemd reports status 203/EXEC. Candidate domains are tried in order; a
# domain the loaded policy lacks fails earlier (229/SELINUX_CONTEXT) and the
# next one is tried, so the canary does not depend on one policy module.
#
# A denial reaches the gate only when the policy blocks it AND does not hide
# it with a dontaudit rule. httpd_t's execve denial is dontaudit on utah
# (#1141), so it was never collected. The loop stops at the first domain whose
# denial the policy audits: an execve denial not hidden by dontaudit, or a read
# of /etc/shadow (shadow_t) that the domain is denied without a dontaudit rule.
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
  echo "canary_output_${type}=${canary_stderr}"

  if [[ "${status}" == "${EXIT_EXEC}" || ( -z "${status}" && "${rc}" == "${EXIT_EXEC}" ) ]]; then
    # execve blocked (203/EXEC): the denial is the execute on bin_t. It reaches
    # the gate only if the policy does NOT hide it with a dontaudit rule (#1141:
    # httpd_t's execve denial is dontaudit on utah, so it was never collected).
    # Skip a domain whose execve denial is hidden and try the next one.
    sesearch --dontaudit -s "${type}" -t bin_t -c file 2>/dev/null | grep -q execute && continue
    break
  elif [[ "${status}" == "1" || ( -z "${status}" && "${rc}" == "1" ) ]]; then
    # cat ran and was denied reading /etc/shadow (shadow_t). That read denial is
    # collected only if the policy denies it without a dontaudit rule. Skip
    # domains that can read shadow or hide the denial, and keep the first whose
    # denial the policy audits.
    sesearch -A -s "${type}" -t shadow_t -c file 2>/dev/null | grep -qw read && continue
    sesearch --dontaudit -s "${type}" -t shadow_t -c file 2>/dev/null | grep -qw read && continue
    break
  else
    # Failed before cat could run (229/SELINUX_CONTEXT for a domain the loaded
    # policy lacks, or any other error): no shadow denial was produced, so skip
    # this domain and try the next one. The old code fell through here and broke
    # on a domain that produced no denial (#1156).
    continue
  fi
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
