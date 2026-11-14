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

> **Guest lane proven; one extension validated:** Just Perfection (run 43612114661). Do **not**
> claim another extension validated until a green run with it staged exists (#909).

## Provenance, image inventory and pre-boot preflight

`gnomeos-*` tags and digests expire two weeks after push, so the lane resolves a digest per run
and the action records it, with the guest `os-release` identity, in `results/guest-provenance.json`.
Stock GNOME OS nightly carries every lane prerequisite except `gnome-ponytail-daemon`, and
`scripts/guest_preflight.py` fails `suite: extensions` closed on that before boot. Evidence,
commands and the full inventory: [gnomeos-guest-provenance.md](gnomeos-guest-provenance.md).

## Provisioned surface

The lane reuses the `gnome-e2e` provisioner (bootc/ostree → `bootc install to-disk` → QEMU/KVM
boot → GDM autologin → ponytail + qecore-headless), pointed at a GNOME OS digest instead of a
Bluefin/Dakota image:

- GNOME OS as a bootc/ostree deployment, with kernel + initramfs extracted from the deployment
  for direct QEMU boot
- GDM autologin for the `bluefin-test` desktop user, which has **no** SSH key, **no** sudo and
  a locked password (isolated session, below)
- **real** GNOME Wayland session (Mutter) + AT-SPI bus (at-spi2-core)
- `gnome-ponytail-daemon` (virtual input) driven by **qecore-headless** — **absent from stock
  GNOME OS**; the [native harness overlay](gnomeos-desktop-canary.md) builds it against
  matching GNOME OS libraries. A successful guest run is still required
- SSH (port 2222 → 22) as the separate `gnome-e2e-harness` account, which alone holds the
  per-run key and sudo, for the harness to drive the guest

## The four hive extensions

| Collection key | UUID |
|---|---|
| `just-perfection` | `just-perfection-desktop@just-perfection` |
| `sjc-gold` | `sjc-gold@binhnguyensoft.com` |
| `shade-inactive-windows` | `shade-inactive-windows-reborn@binhnguyensoft.com` |
| `stock-market` | `stock-market@binhnguyensoft.com` |

Behave collection (`tests/extensions/*`, #914): per-extension features + `extension_lifecycle.feature`.

## Repeatable commands
> **Boot and isolated session have run green** on the [native overlay](gnomeos-desktop-canary.md)
> (canary runs 43549129246 isolated, 43549131789 shared), which bakes in `gnome-ponytail-daemon`
> (blocker 1; stock `gnomeos-nightly` lacks it and has no dnf/rpm). A `suite: extensions` run
> with a staged candidate is green too (run 43612114661, [staging](gnome-extensions-staging.md)).

### 1. Provision, boot, and run in one action invocation

`gnome-e2e` is not a boot-only action: the same invocation provisions the guest **and** runs
`tests/<suite>/features/` inside it (step `Run behave via qecore-headless`). `suite` must
therefore be set — it defaults to `smoke` (the `suite` input), which would boot GNOME OS and run
the **Bluefin** smoke suite, testing the wrong thing. Pass a **digest resolved at dispatch time**, not a tag: the
action hands `inputs.image` verbatim to `podman pull` / `bootc install`.

```yaml
- uses: ./.github/actions/gnome-e2e
  with:
    # needs gnome-ponytail-daemon (blocker 1); digest from a resolve job (gnomeos-guest-provenance.md)
    image: quay.io/gnome_infrastructure/gnome-build-meta@${{ needs.resolve.outputs.digest }}
    suite: extensions   # uses tests/extensions/ (landed with #914)
```

The action installs, preflights (fails today on stock GNOME OS), boots QEMU/KVM, waits for a live
GNOME session, runs `tests/extensions` in the guest and writes `results/` + `vm-serial.log`.

### 2. Confirm a real session (canary)

Run **inside the guest**, over the harness SSH key, while the VM is up. The harness account
drops to the desktop user for session commands:

```bash
ssh -i /tmp/gnome_e2e_key -o StrictHostKeyChecking=no \
    -p 2222 gnome-e2e-harness@127.0.0.1 \
  'sudo -u bluefin-test env XDG_RUNTIME_DIR=/run/user/1001 \
     DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus \
     sh -c "ls /run/user/1001/wayland-*; gnome-extensions list"'
```

A `wayland-N` socket confirms the session (the canary's evidence covers AT-SPI);
`gnome-extensions list` confirms which of the four staged extensions GNOME Shell discovered.

### 3. Re-run individual scenarios in the guest

Step 1 already runs the whole suite. To re-drive one feature, run it **in the guest as the
desktop user**, as the action's isolated branch does — not on the host. qecore-headless is not
used: it needs sudo, which the desktop user must not have. `gnomeos_canary_behave.py` reads the
live session's display, session bus and accessibility bus, then execs behave:

```bash
ssh -i /tmp/gnome_e2e_key -o StrictHostKeyChecking=no \
    -p 2222 gnome-e2e-harness@127.0.0.1 \
  'sudo -u bluefin-test -H -- env -i HOME=/var/home/bluefin-test LANG=C.UTF-8 \
     PATH=/opt/gnomeos-harness/bin:/usr/bin:/bin PYTHONPATH=/tmp/gnome_e2e \
     /opt/gnomeos-harness/bin/python3 /tmp/gnome_e2e/gnomeos_canary_behave.py \
     /opt/gnomeos-harness/bin/behave \
     /tmp/gnome_e2e/tests/extensions/features/extension_lifecycle.feature \
     -D disposable_guest=true --no-capture'
```

Swap in another feature path as needed; re-run the step 2 canary to inspect enabled state.

### 4. Gate the run, against the results copied back to the host workspace

`gnome-e2e` runs the [service gate](#mandatory-service-gate) as a mandatory step
(`if: always() && inputs.suite == 'extensions'`). `extension-validation.yml` calls it with one
staged candidate ([staging](gnome-extensions-staging.md)). Manual form, after a lab boot:

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
scores an all-skipped run green for suites that ship only `@future` scenarios.

## Security posture

The guest is a **test target**, not a trusted host. Extension code runs inside the guest desktop
and must never reach the host, and (maintainer ruling on #908, Option A) must not hold any
guest administration either.

- **Isolated QEMU VM** — no direct host access.
- **No host management sockets** — no Podman/Docker socket, no host D-Bus system bus, no host
  `~/.config` bind-mounted into the guest.
- **No privileged host mounts** — the VM boots from a raw disk written by `bootc install`; the
  host filesystem is not writable from the guest.
- **Isolated session** — `gnome-e2e` with `suite: extensions` (or `isolated-session: 'true'`)
  splits the guest into two accounts with `scripts/guest_accounts.py` before boot:

  | Account | Desktop session | SSH key | sudo | Password |
  |---|---|---|---|---|
  | `bluefin-test` (1001) | GDM autologin; tests and extensions run here | none | none | locked |
  | `gnome-e2e-harness` (1002) | never | per-run key | `NOPASSWD:ALL` | locked |

  The harness home is mode 0700. Behave runs as `bluefin-test` via `sudo -u` with a clean
  environment and without qecore-headless (which calls sudo). The harness never runs a file the
  desktop user can write with elevated rights: the checker lives in the harness home, and a
  pre-existing `/tmp/gnome_e2e` (even a symlink) fails the run.
- **Proven on the booted guest** — before any test, `scripts/guest_session_isolation.py` (as
  root) checks the desktop user has no sudo, privileged group, password, SSH key, sshd key path
  or polkit grant, the harness home is closed, and no host-share mount or docker/podman/libvirt
  socket exists (full list in the script). Report: `session-isolation.json`, outside `results/`;
  guest `results/` return as regular files only, never overwriting harness files. Any failure
  stops the run. Accepted exception: `/dev/uinput` is 0666 for the virtual input.

Limits that remain: a candidate shares a uid with behave, so it could alter that run's
`results/`; the image's own polkit defaults for the active local session are unchanged; and
QEMU user networking still lets the guest open connections to the runner, which has no
management service listening. Shared mode (all other suites) still gives `bluefin-test` the key
and sudo; never run candidate extensions there.

A host socket, key, or mount exposed to the guest desktop is a regression: stop and file an issue.

## Status

- [x] Provenance: tested build recorded per run in `results/guest-provenance.json`
- [x] Provenance: `scripts/build-gnomeos-harness.sh` resolves digests per run (`harness-provenance.json`)
- [x] Guest inventory verified against the image layers; four hive extensions documented
- [x] Pre-boot preflight (`scripts/guest_preflight.py`) fails closed on missing prerequisites
- [x] Mandatory service gate implemented and unit-tested (`scripts/extension_validation.py`)
- [x] Security posture recorded: no host reach
- [x] Isolated session (Option A): separate harness account, desktop user with no key/sudo,
      checked on the booted guest by `scripts/guest_session_isolation.py`. Run green on GNOME
      OS: canary run 43549129246 (`isolated-session: true`; any failed check stops the run),
      `session-isolation.json` in its `gnomeos-desktop-canary` artifact
- [x] Gate wired into the lane as a mandatory `gnome-e2e` step for `suite: extensions` (#991)
- [x] Repeatable boot + load + run validated on GitHub runners: `extension-validation.yml`
      (run 43612114661); the ponytail overlay is `scripts/build-gnomeos-harness.sh`
- [x] Exact candidate ZIP built offline, hash-checked, staged before boot ([staging](gnome-extensions-staging.md))
- [x] At least one green extension-validation run captured: run 43612114661 (Just Perfection)
- [ ] Lane closed
