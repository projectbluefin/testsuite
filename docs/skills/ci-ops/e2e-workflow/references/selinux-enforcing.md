---
name: selinux-enforcing
description: "How the e2e QEMU guest is qualified with SELinux enforcing: labeling, mode checks, AVC gate, canary."
metadata:
  type: reference
  audience: agents
  maturity: experimental
---
# SELinux enforcing in the e2e guest

`e2e.yml` boots the candidate with its own SELinux mode. There is no
`selinux=0`, `enforcing=0` or `enforcing=1` on the kernel command line: the
first two hide policy regressions, the last hides a candidate that ships
permissive. Helpers live in `scripts/selinux_qualify.py` and
`scripts/selinux_collect_avc.sh` (both in the sparse checkout). Evidence is
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
   `seclabel` option.
3. Re-scan; anything still unlabeled fails the step.

Never fix a denial by relabeling the whole tree, `-F` over candidate files,
`chcon` to a broad type, `setenforce 0`, or a permissive domain.

## AVC collection and canary

`selinux_collect_avc.sh` runs in the guest as root and prints AVC/USER_AVC
records from `ausearch` (when auditd has a log) and the whole journal (all
kept boots). `selinux_qualify.py` de-duplicates by audit serial.

After the scenario log is judged, the gate starts a transient unit in
`httpd_t` that runs `/usr/bin/cat /etc/shadow` with output discarded. The
policy forbids that (entrypoint or read), so a new `httpd_t` denial must
appear and must fail the gate. If it does not, collection is broken and the
step fails: a clean gate would prove nothing.

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
