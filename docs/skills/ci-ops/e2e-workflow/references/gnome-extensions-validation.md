---
name: gnome-extensions-validation
description: "Deep dive: GNOME OS guest lane for the developer extension-validation service"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# GNOME OS Extension-Validation Lane (#908)

## Purpose

Validate GNOME developer extensions against a **real GNOME OS Wayland session** with a **real
AT-SPI bus** and **real virtual input** — not the Bluefin desktop and not a mock. Candidates
must be staged into the guest filesystem before GNOME Shell starts so extensions are discovered
at session initialization. The four `gnome-extensions-hive` extensions are installed, enabled,
and exercised with a qecore/Behave input+AT-SPI scenario.

> **No run has completed yet.** Do **not** claim GNOME OS extension validation as done until a
> green run exists and its evidence is attached.

## Pinned provenance (do not float)

Base image `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-nightly`. The lane consumes the
**digest reference**, never the tag:

| Tag | Digest |
|---|---|
| `gnomeos-nightly` (pinned for the lane) | `sha256:57eeef917d057e37d8d5824fab195ebf3b0ad49fc1ca191b7bc02b82418ed981` |
| `gnomeos-51` / `gnomeos-50` / `gnomeos-latest` | reference only |

Resolved 2026-09-30; proves **existence**, not a successful boot with this action's provisioner.
Re-derive after any change with `skopeo inspect docker://…:gnomeos-nightly | jq -r '.Digest'`.

## Guest inventory

The lane reuses the `gnome-e2e` provisioner (bootc/ostree → `bootc install to-disk` → QEMU/KVM
boot → GDM autologin → ponytail + qecore-headless), pointed at `gnomeos-nightly` instead of a
Bluefin/Dakota image. Provisioned surface:

- GNOME OS nightly (pinned digest) as a bootc/ostree deployment, with kernel + initramfs
  extracted from the deployment for direct QEMU boot
- GDM autologin for the `bluefin-test` user; passwordless sudo for test automation
- **real** GNOME Wayland session (Mutter) + AT-SPI bus (at-spi2-core)
- `gnome-ponytail-daemon` (virtual input) driven by **qecore-headless** — **absent from stock
  `gnomeos-nightly`**; required baked into the OCI image (`action.yml:14`) and no overlay
  supplying it exists yet, so it is an input to the lane, not a lane output
- SSH (port 2222 → 22) as `bluefin-test` for the harness to drive the guest
- No Fedora dnf/RPM assumption — GNOME OS has no package manager; tooling must ship in a test
  overlay/sysext

## The four hive extensions

| Collection key | UUID |
|---|---|
| `just-perfection` | `just-perfection-desktop@just-perfection` |
| `sjc-gold` | `sjc-gold@binhnguyensoft.com` |
| `shade-inactive-windows` | `shade-inactive-windows-reborn@binhnguyensoft.com` |
| `stock-market` | `stock-market@binhnguyensoft.com` |

Their Behave collection (`tests/extensions/*`, PR #914, a separate slice) has per-extension
behaviour features plus a cross-cutting `extension_lifecycle.feature`.

## Repeatable commands
> **UNVERIFIED — do not copy-paste as proven.** Nothing below has been executed end-to-end. Two
> hard blockers stand between this snippet and a real run:
>
> 1. **`tests/extensions/` does not exist at this head** (lands with #914), so `suite: extensions`
>    makes the action's sparse checkout (`action.yml:76`) and its `scp` of
>    `_testsuite/tests/${GNOME_E2E_SUITE}` (`action.yml:373`) resolve to nothing, and the run fails.
> 2. **Stock `gnomeos-nightly` has no `gnome-ponytail-daemon`.** The action requires it baked into
>    the OCI image (`action.yml:14`) — there is no dnf/rpm in the guest — and this lane ships **no
>    overlay/sysext that supplies it**. That overlay is unfinished work, not a documented step.
>
> Treat the commands as intended shape only; replace with the exact commands executed once a lab
> run succeeds.

### 1. Provision, boot, and run in one action invocation

`gnome-e2e` is not a boot-only action: the same invocation provisions the guest **and** runs
`tests/<suite>/features/` inside it under `qecore-headless` (`action.yml:384`). `suite` must
therefore be set — it defaults to `smoke` (`action.yml:35-37`), which would boot GNOME OS and run
the **Bluefin** smoke suite, testing the wrong thing. Pass the **pinned digest**, not a tag: the
action hands `inputs.image` verbatim to `podman pull` / `bootc install`.

```yaml
- uses: ./.github/actions/gnome-e2e
  with:
    # requires an image that carries gnome-ponytail-daemon (blocker 2 above)
    image: quay.io/gnome_infrastructure/gnome-build-meta@sha256:57eeef917d057e37d8d5824fab195ebf3b0ad49fc1ca191b7bc02b82418ed981
    suite: extensions   # requires tests/extensions/ from #914 (blocker 1 above)
```

The action runs `bootc install to-disk`, extracts kernel/initramfs, boots a KVM QEMU VM, waits for
SSH then a live GNOME session, copies `tests/extensions` (plus `tests/shared`) into the guest, runs
behave there, and writes `results/` + `vm-serial.log` into the workspace.

### 2. Confirm a real session (canary)

Run **inside the guest**, over the harness SSH key, while the VM is up:

```bash
ssh -i /tmp/gnome_e2e_key -o StrictHostKeyChecking=no \
    -p 2222 bluefin-test@127.0.0.1 bash -l <<'REMOTE'
  source /tmp/gnome_e2e_session.env
  echo "session=$XDG_SESSION_TYPE display=$WAYLAND_DISPLAY"
  gdbus call --session --dest org.a11y.atspi.Registry \
    --object-path /org/a11y/atspi --method org.a11y.atspi.Registry.GetRegistry 2>&1 | head -1
  gnome-extensions list
REMOTE
```

`session=wayland` and a non-empty AT-SPI registry reply confirm the real session and AT-SPI.
`gnome-extensions list` is the pre-install inventory: the guest boots stock GNOME OS, so the four
hive extensions are installed by `extension_lifecycle.feature` during the run and are **not**
expected here beforehand. Provision failures are infrastructure errors, never green.

### 3. Re-run individual scenarios in the guest

Step 1 already runs the whole suite. To re-drive one feature, run it **in the guest under
`qecore-headless`** — not on the host, and not bare `behave`: the scenarios need the guest's
Wayland session, AT-SPI bus, and ponytail virtual input that only `qecore-headless` sets up.
Mirrors `action.yml:384`:

```bash
ssh -i /tmp/gnome_e2e_key -o StrictHostKeyChecking=no \
    -p 2222 bluefin-test@127.0.0.1 '
  set -e
  source /tmp/gnome_e2e_session.env
  export PATH=$HOME/.local/bin:$PATH
  export PYTHONPATH=/tmp/gnome_e2e
  $HOME/.local/bin/qecore-headless \
    "$(which behave) /tmp/gnome_e2e/tests/extensions/features/extension_lifecycle.feature \
       --format json.pretty --outfile /tmp/gnome_e2e/results/results.json --no-capture"
'
```

Swap in another per-extension feature path as needed. Re-run the `gnome-extensions list` canary
after `extension_lifecycle.feature`; it must now list the four hive extensions.

### 4. Gate the run, against the results copied back to the host workspace

> **Not wired yet.** No workflow, Justfile recipe, or `gnome-e2e` action step invokes
> `scripts/extension_validation.py` at this head — the action's summarise step uses
> `scripts/e2e_summary.py` only. Today the gate is run by hand against the copied-back
> `results/`. Wiring it into the lane as the mandatory service gate is a follow-up slice of #908.

```bash
python3 scripts/extension_validation.py results/results.json; echo $?
# 0 = genuine pass; 1 = empty/all-skipped/undefined/hook-error/failed-boot/missing-result
```

## Mandatory service gate

A run passes only if **at least one scenario genuinely passed and nothing errored**. Implemented in
`scripts/extension_validation.is_extension_validation_pass`; **fails closed** for:

- **empty** — no scenarios at all; **all-skipped** — every scenario skipped, none passed
- **undefined / untested** — steps not implemented
- **hook-error / failed-boot / error** — any `error` / `hook_error` (lands in `other`)
- **missing-result** — no `results.json` (a failed boot produced no run)
- **any other non-success status** — the non-success set derives from
  `e2e_summary.SUCCESS_STATUSES`, so a future behave status fails this gate too

Deliberately stricter than the general e2e headline (`scripts/e2e_summary.is_success`), which
scores an all-skipped or empty run green for suites that ship only `@future` scenarios.

## Security posture

The guest is a **test target**, not a trusted host. Extension code runs inside the guest desktop
and must never reach the host:

- **Isolated QEMU VM** — no direct host access.
- **No host management sockets** — no Podman/Docker socket, no host D-Bus system bus, no host
  `~/.config` bind-mounted into the guest.
- **No privileged host mounts** — the VM boots from a raw disk written by `bootc install`; the
  host filesystem is not writable from the guest.
- **Credentials are guest-local and disposable** — the harness SSH key (`authorized_keys` in the
  `bluefin-test` home, `action.yml:215`) and the `bluefin-test` autologin let the harness drive
  the guest. Extension code runs in `gnome-shell` **as `bluefin-test`**, who also has
  `NOPASSWD:ALL` sudo (`action.yml:224-226`), so extension code **can** read that key and escalate
  **inside the guest**. Accepted: the key is generated per run, authorises nothing but this
  throwaway VM, and grants no reach back to the host. Never reuse a long-lived or host-valid
  credential here.

A host socket, key, or mount exposed to the guest desktop is a regression: stop and file an issue.

## Status

- [x] Official GNOME OS nightly pinned (digest above)
- [x] Guest inventory + four hive extensions documented
- [x] Mandatory service gate implemented and unit-tested (`scripts/extension_validation.py`)
- [x] Security posture recorded: guest-local, disposable credentials; no host reach
- [ ] Gate wired into the lane (no workflow / action step invokes
      `scripts/extension_validation.py` yet; run by hand today)
- [ ] Repeatable boot + load + run commands validated in the lab (**unverified**; blocked
      on `tests/extensions/` (#914) and a `gnome-ponytail-daemon` overlay)
- [ ] At least one green extension-validation run captured and attached
- [ ] Lane closed
