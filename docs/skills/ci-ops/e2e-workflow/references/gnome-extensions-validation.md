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

Their Behave collection (`tests/extensions/*`, landed via #914) has per-extension
behaviour features plus a cross-cutting `extension_lifecycle.feature`.

## Repeatable commands
> **UNVERIFIED — do not copy-paste as proven.** Nothing below has been executed end-to-end. One
> hard blocker stands between this snippet and a real run:
>
> 1. **Stock `gnomeos-nightly` has no `gnome-ponytail-daemon`.** The action requires it baked into
>    the OCI image — there is no dnf/rpm in the guest. The native overlay and baseline
>    caller are described in [gnomeos-desktop-canary.md](gnomeos-desktop-canary.md);
>    neither a successful boot nor candidate credential isolation is established yet.
>
> Treat the commands as intended shape only; replace with the exact commands executed once a lab
> run succeeds.

### 1. Provision, boot, and run in one action invocation

`gnome-e2e` is not a boot-only action: the same invocation provisions the guest **and** runs
`tests/<suite>/features/` inside it (step `Run behave via qecore-headless`). `suite` must
therefore be set — it defaults to `smoke` (the `suite` input), which would boot GNOME OS and run
the **Bluefin** smoke suite, testing the wrong thing. Pass a **digest resolved at dispatch time**, not a tag: the
action hands `inputs.image` verbatim to `podman pull` / `bootc install`.

```yaml
- uses: ./.github/actions/gnome-e2e
  with:
    # requires an image that carries gnome-ponytail-daemon (blocker 1 above);
    # digest from a not-yet-written `resolve` job (sketch: gnomeos-guest-provenance.md); expires in 2 weeks
    image: quay.io/gnome_infrastructure/gnome-build-meta@${{ needs.resolve.outputs.digest }}
    suite: extensions   # uses tests/extensions/ (landed with #914)
```

The action runs `bootc install to-disk`, runs the guest preflight (fails here today on stock GNOME
OS: no `gnome-ponytail-daemon`), extracts kernel/initramfs, boots a KVM QEMU VM, waits for
SSH then a live GNOME session, copies `tests/extensions` (plus `tests/shared`) into the guest, runs
behave there, and writes `results/` (including `guest-provenance.json`) + `vm-serial.log` into
the workspace.

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

A `wayland-N` socket confirms the session; the canary's own evidence covers AT-SPI.
`gnome-extensions list` is the pre-run inventory to confirm the four extensions are staged
and discoverable before GNOME Shell starts (or verify which are discovered).

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

Swap in another per-extension feature path as needed. Re-run the `gnome-extensions list` canary
after `extension_lifecycle.feature` to inspect active and enabled state.

### 4. Gate the run, against the results copied back to the host workspace

The `gnome-e2e` action runs the gate as its own **mandatory service-gate step**
(`.github/actions/gnome-e2e/action.yml`, `if: always() && inputs.suite == 'extensions'`):
a `suite: extensions` run fails the job on any empty / all-skipped / undefined /
untested / hook-error / failed-boot / missing-result result, regardless of the general
`scripts/e2e_summary.py` headline (which scores an all-skipped run green). No workflow or
Justfile recipe in this repo calls the action with `suite: extensions` yet — a consumer
runs it directly. The command below is still the manual form (re-run after a lab boot):

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

  The harness home is mode 0700. Behave runs as `bluefin-test` through `sudo -u` from the
  harness account, with a clean environment and without qecore-headless, which calls sudo
  itself. The harness never runs a file the desktop user can write with elevated rights: the
  checker lives in the harness home, and `/tmp/gnome_e2e` must be newly created by the harness
  (a pre-existing name, even a symlink, fails the run).
- **Proven on the booted guest** — before any test runs, `scripts/guest_session_isolation.py`
  runs as root and checks that the desktop user has no sudo (`sudo -l -U`), no admin group, a
  locked password and no `authorized_keys`; that the harness home is closed; and that there is
  no 9p/virtiofs/network share mount and no container socket. Its report is
  `session-isolation.json` (outside `results/`, which the session fills); any failure stops the
  run.

Limits that remain: a candidate shares a uid with behave, so it could alter that run's
`results/`; the image's own polkit defaults for the active local session are unchanged; and
QEMU user networking still lets the guest open connections to the runner, which has no
management service listening. Shared mode (all other suites) still gives `bluefin-test` the key
and sudo; never run candidate extensions there.

A host socket, key, or mount exposed to the guest desktop is a regression: stop and file an issue.

## Status

- [x] Provenance contract: tested build recorded per run in
      `results/guest-provenance.json` (static pins expire after 2 weeks)
- [ ] Provenance contract: resolve job that pins the digest per run
      (sketched in `gnomeos-guest-provenance.md`; no workflow does this yet)
- [x] Guest inventory verified against the image layers; four hive extensions documented
- [x] Pre-boot preflight (`scripts/guest_preflight.py`) fails closed on missing prerequisites
- [x] Mandatory service gate implemented and unit-tested (`scripts/extension_validation.py`)
- [x] Security posture recorded: no host reach
- [x] Isolated session (Option A): separate harness account, desktop user with no key/sudo,
      checked on the booted guest by `scripts/guest_session_isolation.py`. **Not yet run on
      GNOME OS**: dispatch the canary with `isolated_session=true` and attach its
      `session-isolation.json` and desktop evidence
- [x] Gate wired into the lane: `gnome-e2e` runs `scripts/extension_validation.py` as a
      mandatory step when `suite == 'extensions'` (#991). No repo workflow/recipe calls the
      action with `suite: extensions` yet — a consumer runs it directly.
- [ ] Repeatable boot + load + run commands validated in the lab (**unverified**;
      tests/extensions landed with #914; blocked on a `gnome-ponytail-daemon` overlay, which the
      preflight now reports by name)
- [ ] At least one green extension-validation run captured and attached
- [ ] Lane closed
