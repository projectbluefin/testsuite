---
name: bootc
version: "1.0"
last_updated: "2026-09-15"
id: bootc
one_line_purpose: Write bootc upgrade, rollback, and migration tests.
entry_point: docs/skills/test-authoring/bootc/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [bootc, lifecycle, rollback]
description: "How to write bootc upgrade, rollback, and migration tests for the testsuite repo. Load when editing bootc-related .feature files or steps."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# bootc Lifecycle Testing Reference

Load when: writing or debugging lifecycle, upgrade, or rollback tests.

## bootc status JSON schema (v1alpha1)

```
bootc status --format=json
```

| Field | Path |
|---|---|
| Active deployment | `.status.booted` |
| Pending reboot | `.status.staged` (null if none) |
| Active image digest | `.status.booted.image.imageDigest` |
| Active image ref string | `.status.booted.image.image.image` |
| Pinned (won't auto-prune) | `.status.booted.pinned` (bool) |

**Wrong paths that cause silent test skips:**
- `.staged` (missing `.status` prefix)
- `.active.imageDigest`
- `.active.image`

Always validate the outer structure before accessing:
```python
payload = json.loads(output)
assert isinstance(payload.get("status"), dict), "bootc status JSON malformed"
booted = payload["status"]["booted"]
```

Bare `payload.get("status", {})` silently accepts malformed JSON — don't use it as a guard.

## Lifecycle capture pattern

Capture digests at the right moments or verification steps silently skip:

```python
# 1. Before upgrade — save current digest
original_digest = get_booted_digest(context)

# 2. Trigger upgrade (bootc upgrade / image swap)

# 3. After upgrade, BEFORE reboot — capture staged digest
expected_upgrade_digest = get_staged_digest(context)

# 4. Reboot VM

# 5. After reboot — assert booted == expected_upgrade_digest
```

Without step 3, the post-reboot assertion has nothing to compare against and silently passes or skips.

## ostree admin status parsing

```
* <ref>    ← active/booted deployment (exactly one)
  <ref>    ← previous deployments (2-space indent, no leading *)
```

Counting `* ` lines gives 1, never 2. To count **all** deployment headers:
```python
import re
count = len(re.findall(
    r'^(?:\* |\s{2}(?!\s))(?=[a-zA-Z0-9])',
    output,
    re.MULTILINE
))
assert count >= 2  # not == 2; multiple upgrades can produce more
```

Assert `>= 2`, not `== 2` — after multiple upgrades there can be more than two deployment entries.

## bootc pin / unpin

`sudo bootc pin` sets `.status.booted.pinned = true` — the deployment is protected from auto-pruning.  
`sudo bootc pin --unpin` clears it.

Step definitions in `tests/lifecycle/features/steps/steps.py`:
```
* bootc status shows deployment is pinned
* bootc status shows deployment is not pinned
```

Both use `_parse_bootc_status(context)` for validated JSON access — do not duplicate the bare `json.loads` pattern.

## Settled-deployment barrier pattern

In fresh QEMU installs or after deployment mutations, `bootc pin` races the
staged-deployment writer or early-boot finalization. `bootc status` cannot
reliably report the previous or updated pin state while staging or finalization
is in progress.

Always insert the settled-deployment barrier step before mutating or asserting
deployment pin state:

```gherkin
* Bluefin VM is booted and reachable over SSH
* Deployment is settled
* Run SSH command: "sudo bootc pin"
```

The barrier step (`Deployment is settled` / `bootc deployment is settled`) polls
`sudo bootc status --format=json` over SSH until:
1. `sudo bootc status --format=json` returns exit code 0 with valid JSON.
2. `.status.booted` is present and valid.
3. `.status.staged` is `null`/absent (no staging or finalization in progress).

The step enforces a bounded deadline (default 120s, 5s poll interval) and emits
a clear diagnostic failure message if the deployment does not settle. A custom
timeout variant is also available:
`* Deployment is settled within 60 seconds`.


## Flatcar: verifying Ignition ran

Ignition executes **in the initramfs**, so its systemd units (`ignition-*.service`,
`ignition-complete.target`) are not visible from the booted root. Do not assert on
`systemctl status ignition-*` — those checks pass vacuously.

The observable proof of a successful run is the ESP first-boot marker. GRUB sets
`flatcar.first_boot=detected` when `flatcar/first_boot` exists on the EFI System
Partition, and Ignition deletes that file only after it completes successfully:

```gherkin
* Flatcar ESP is mounted at /boot
* Ignition first-boot marker is cleared
* Ignition-provisioned SSH keys are present for the test user
```

**Always assert the ESP is mounted first.** `/boot/flatcar/first_boot` is checked for
*absence*; if `/boot` were not mounted the absence check would pass trivially. The
`Flatcar ESP is mounted at /boot` step asserts `findmnt -no FSTYPE /boot` reports
`vfat`, which closes that false-pass hole.

SSH-key placement differs by image age — Ignition writes either
`~/.ssh/authorized_keys` or an `~/.ssh/authorized_keys.d/` fragment (the
`update-ssh-keys` layout). Accept both and assert on the return code; never parse
the key file's contents.

## Flatcar: disabling automatic updates

There is **no `update_strategy` setting in Flatcar.** The two real knobs both live in
`/etc/flatcar/update.conf`:

| Key | Effect |
|---|---|
| `SERVER=disabled` | Disables automatic updates (upstream's recommended switch; what `flatcar-update --disable-afterwards` writes) |
| `REBOOT_STRATEGY=off` | Update is still downloaded to the passive partition; only the *reboot* is suppressed |

Upstream explicitly discourages masking `update-engine.service` / `locksmithd.service`,
because a masked `update-engine` cannot mark a freshly booted partition successful and
GRUB then rolls back. So `systemctl is-active update-engine` is **not** a valid
"updates are disabled" assertion — after disabling, the unit must still be `active`.

Parse `update.conf` with `parse_update_conf()` / `automatic_updates_disabled()` in
`tests/flatcar/features/steps/steps.py` rather than grepping. It is a shell-sourced
`KEY=VALUE` fragment: values may be quoted, `#` comments are ignored, and later
assignments win.

Any scenario that mutates `update.conf` must back it up first and restore it in both
an explicit final step *and* `after_scenario`, so a mid-scenario failure cannot leave
the VM with updates permanently off.

## Flatcar: what still needs the lab

Booting the disk that `knuckle` just installed to requires swapping the KubeVirt VM's
boot device. That lives in the VM spec, owned by `projectbluefin/lab`, not this repo.
Without it a reboot silently returns to the live rootdisk and the scenario passes while
testing nothing — which is why that scenario stays `@future` rather than being written
optimistically.
