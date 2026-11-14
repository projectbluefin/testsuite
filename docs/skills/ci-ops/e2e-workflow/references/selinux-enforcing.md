---
name: selinux-enforcing
description: "How the e2e QEMU guest is qualified with SELinux enforcing: labeling, mode checks, AVC gate, canary."
metadata:
  type: reference
  audience: agents
  maturity: experimental
---
# SELinux enforcing in the e2e guest

The lane is on by default: `selinux_enforcing` defaults to `true` in both
`e2e.yml` and `manual.yml` (#1024, rollout in #1021). Callers may pass
`selinux_enforcing: false` to fall back to the legacy `selinux=0` boot, in
which case every step below is skipped; use that only to triage, not to make
a candidate pass.

When enabled, `e2e.yml` boots the candidate with its own SELinux mode. There
is no `selinux=0`, `enforcing=0` or `enforcing=1` on the kernel command line:
the first two hide policy regressions, the last hides a candidate that ships
permissive. Helpers live in `scripts/selinux_qualify.py`,
`scripts/selinux_collect_avc.sh` and `scripts/selinux_canary.sh` (all in the
sparse checkout). Evidence is
written to `results/selinux/` and uploaded with the results artifact.

## Contract

| Stage | Step | Fails when |
|-------|------|------------|
| Expected mode | install step, `expected-mode` | never; any deployment with `etc/selinux/<SELINUXTYPE>/contexts/files/file_contexts` expects `enforcing`, otherwise `unsupported` (freedesktop-sdk images) |
| Labeling | install step, before unmount | a harness-created file is still unlabeled after `setfiles` |
| After boot | **Verify SELinux enforcing** | `getenforce` is not `Enforcing` (or is `Enforcing` on an `unsupported` image) |
| After suite | **SELinux denial gate** | still not enforcing (covers lifecycle reboots); any enforced AVC not in `selinux_allowlist.yaml`; the canary is not seen |

`permissive=1` denials (permissive domains in the candidate policy) are
printed as warnings and recorded, not failed: the operation was not blocked.

## Labeling harness files

The runner has no SELinux, so the files the install step writes under each
deployment's `etc` and under `var` (`passwd` and `group` edits via `sed -i`,
sshd drop-in, host keys, sudoers, GDM/SDDM config, masked-unit symlinks, the
`bluefin-test` home) have no `security.selinux` xattr and would be
`unlabeled_t` in the guest. Only those two trees are scanned and relabeled.
The fallback `boot.N` symlinks under `/ostree/boot.*` stay unlabeled; they are
read only by `ostree`/`bootc`, which run unconfined.

1. Before any injection, record paths under each deployment's `etc/` and the
   stateroot `var/` that are already unlabeled (`baseline-unlabeled-*.txt`).
   These are candidate-owned and are **not** relabeled, so a candidate
   labeling defect stays a product failure.
2. After injection, list unlabeled paths not in the baseline
   (`harness-labeled-*.txt`) and label them with the **candidate's** own
   `setfiles` and `file_contexts`, run in a privileged container of the
   image: `setfiles -m -F -r <root> -f <list> <file_contexts>`. `-r` strips
   the deployment or stateroot prefix so `.../default/var/home/...` matches
   `/var/home/...`. `-m` is required because the runner's mounts carry no
   `seclabel` option. The container sees the disk at `/harness/root`
   (and the list at `/harness/list`), not at `/mnt/root`: in ostree-style
   images `/mnt` and `/home` are symlinks into an unpopulated `/var`, so
   podman cannot create mount points there (`utah:testing` failed with
   "crun: creating `/mnt/root`"). The step rewrites `/mnt/root` to
   `/harness/root` in the root, the `file_contexts` path and every list entry.
3. Re-scan; anything still unlabeled fails the step.

Never fix a denial by relabeling the whole tree, `-F` over candidate files,
`chcon` to a broad type, `setenforce 0`, or a permissive domain.

The harness's injected `/etc/tmpfiles.d/ci-user.conf` creates the test home
and its `.ssh` with non-recursive `d` entries, which also set their mode,
owner and label on later boots. Don't add a recursive `Z` rule for the home.
Once the runner container is loaded, the home holds Podman storage, and `Z`
makes `systemd-tmpfiles` walk its hardlinks on every later boot. That produced
`systemd_tmpfiles_t` → `proc_security_t` denials (reading
`/proc/sys/fs/protected_hardlinks`) on every boot after the first. Found by
#1205; run 43535082068 has none of them once the rule is gone.

## AVC collection and canary

`selinux_collect_avc.sh` runs in the guest as root and prints AVC/USER_AVC
records from `ausearch` (or the raw `audit.log` when `ausearch` is missing),
the whole journal (all kept boots) and the kernel ring buffer (`dmesg`).
`selinux_qualify.py` de-duplicates by audit serial.
The collector is piped to `bash -s` over SSH. Always pass `--input-logs`
to `ausearch`: otherwise it reads the remaining script from stdin instead of
the audit logs, preventing the journal and kernel-buffer collection from running.

After the scenario log is judged, `selinux_canary.sh` starts a transient unit
in a confined domain that runs `/usr/bin/cat /etc/shadow` with output
discarded. It tries `httpd_t`, then `sshd_t`, `getty_t`, `syslogd_t` and
`chronyd_t`, and stops at the first one whose unit ends with status
`203/EXEC` (the policy blocked execve). A domain the loaded policy lacks
ends with `229/SELINUX_CONTEXT` and the next one is tried. A new denial in
any tried domain must appear and must fail the gate.

The canary script also prints `key=value` diagnostics: each attempt's
`systemd-run` exit code (`attempt_<domain>`) and output (`canary_output_<domain>`), `/proc/cmdline`, `seinfo -t httpd_t`
(when `seinfo` exists), whether `/var/log/audit/audit.log` exists, `auditd`
and `auditctl -s` state, and AVC counts from `journalctl -k`, the whole
journal and `dmesg`. The gate adds the SSH and collector exit codes, writes
everything to `results/selinux/canary-diagnostics.txt` and the step summary,
and `selinux_qualify.py canary --diagnostics` names the failure (#1141):

| Reason | Meaning |
|--------|---------|
| `not-run` | Every attempt failed before execve (e.g. 229/SELINUX_CONTEXT), or the guest returned no diagnostics. |
| `not-collected` | The AVC collector itself failed. |
| `unknown` | execve failed (203/EXEC), `cat` exited non-zero after execve in any attempt, or a probe read the file (status 0), but no denial was collected; the exit code does not show SELinux caused it. Read the per-attempt output and evidence fields, and check for a `dontaudit` rule. |
| `permissive` / `allowlisted` | The denial was collected but did not fail the gate. |

Any of these fails the step: a clean gate would prove nothing.

## Allowlist

`selinux_allowlist.yaml` entries match on SELinux **type** of
`source_context` and `target_context`, the exact permission set, `comm`, and
`tclass` when given. `reason` is required; link `upstream_bug` when there is
one. Prefer filing the denial against the owning image repo over adding an
entry. An entry broad enough to match the canary defeats the canary.

## Known gaps

- Not yet proven on a hosted run; dispatch `manual.yml` with `smoke` and a
  `lifecycle` suite before relying on it.
- The security suite (`tests/security`) has its own SELinux scenarios; its
  reachability is tracked separately (#704).
