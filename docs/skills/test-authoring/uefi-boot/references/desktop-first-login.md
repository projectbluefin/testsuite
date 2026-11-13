---
name: desktop-first-login
description: "Proposed firmware boot and desktop first-login qualification contract for issue #1026."
metadata:
  type: reference
  audience: agents
  maturity: draft
---

# Desktop firmware boot and first-login qualification

Status: proposed design for [#1026](https://github.com/projectbluefin/testsuite/issues/1026).
This document supplies a reviewable fixture contract and acceptance cases. It
does not add runtime coverage or approve a suite, privileged fixture, secrets,
or workflow permissions. Hosted evidence and per-image approval are outstanding.

## Scope and existing evidence

The fast desktop smoke lane checks a prepared user session. Its direct-kernel
boot and injected account/autologin cannot establish firmware boot, account
creation, or password authentication. Keep those claims separate in results.

Reuse the [OOBE investigation](../../../../archive/spikes/oobe-first-boot.md)
and [UEFI spike](../../../../archive/spikes/uefi-ovmf-boot.md).
The spike workflow installs systemd-boot and seeds an SSH user. It is a migration
experiment, not proof of the shipped loader or the no-user first-use journey.
The archived GIS mock-mode recommendation covers only wizard UI. Neither is a
passing qualification result for this contract.

Propose one opt-in x86_64 GitHub Actions qualification job, initially on a single
approved Bluefin desktop disk, with OVMF and software rendering. No Secure Boot,
TPM, physical GPU, installer matrix, or server installation claims. Coordinate
firmware fixture ownership with #706; keep native Server installer work in #975.

## Image admission: approve a journey before running

An OCI tag alone is insufficient: how a disk was installed determines whether
a user already exists. Record both immutable image identity and the supported
disk preparation route. Do not infer GIS availability from the desktop name.

| Target | Proposed admission scope | Required journey evidence before admission |
|---|---|---|
| Bluefin desktop, one pinned build | First candidate; not yet admitted | Inspect supported installed disk, GDM configuration, GIS package/vendor policy and initial accounts; record native page sequence or supported credential provisioning route |
| Bluefin LTS and hardware/developer variants | Deferred; no inherited pass from Bluefin | Independent disk and vendor-policy inspection for each admitted build/profile |
| Dakota desktop | Deferred; no substitute for an unreachable Bluefin candidate | Independent loader, display-manager and first-use inspection |
| GNOME OS | Outside initial scope | A different image cannot establish Bluefin first-login coverage |
| No-OOBE desktop profiles | Eligible only with an explicit supported credential route | Identify how users normally create/provision credentials and which native greeter authenticates them |
| Server, headless and KDE profiles | Outside this bounded GNOME design | No desktop result inferred from SSH health or another display manager |

## Admission record and unreachable journeys

The admission record must name the image digest, disk checksum and preparation
recipe/version, loader identity, display manager, initial regular-user inventory
(no shadow/password data), GIS vendor configuration and expected ordered required
screens, locale/keyboard settings, and expected final user/session properties.
For no-OOBE images, name the supported credential provisioning method and state
explicitly that this profile proves login, not UI account creation.

If no supported disk can reach the claimed journey, record `unreachable` with
serial/UI evidence and fail qualification. Do not force GIS with a debug kernel
argument, change vendor page policy, seed a user for a GIS profile, swap images,
or convert the run into a smoke pass. Maintainers approve this admission record
before runtime implementation is treated as image qualification.

### Admission record: utah:testing (first candidate, #1026)

Inspected 2026-11-12, read-only, from the registry and the sources of utah,
utah-packages and projectbluefin/common, plus baselines. No container was run, so anything that needs a boot is marked
**to confirm by probe** (#1179). Each probe run pins its own digest and
records it. Treat the digest below as the one inspected, not a fixed pin.

| Field | Record |
|---|---|
| Image | `ghcr.io/projectbluefin/utah:testing@sha256:bb9aea734d6a099444067af29c0783057465f0779ffc058bae4014b4a1cd97e0` (manifest digest of `:testing` at inspection) |
| Disk preparation | `bootc install to-disk` as in `.github/workflows/e2e.yml`, but with **no seeded user, no GDM auto-login and no SSH user**. Only the per-run root key decided on #1026. The bootloader step must succeed; there's no `-kernel` fallback. Disk checksum: recorded per run by the probe |
| Loader | shim → GRUB via bootupd: `shim-x64` 16.1, `grub2-efi-x64` 2.12, `bootupd` 0.3.2 (utah `baselines/utah/rpms.tsv`; `bootupctl` and `bootloader-update.service` are in `baselines/utah/surface.tsv`). Not systemd-boot. **To confirm by probe:** the ESP contents after install |
| Display manager | GDM 51.0 (`gdm.service`). The image itself sets no auto-login: utah's `AutomaticLogin` and `custom.conf` edits are in `iso/live/src/configure-live.sh` only, i.e. the live ISO, not an installed disk |
| Initial regular users | Expected **none** (no uid ≥ 1000). The live ISO's `liveuser` is created by the ISO scripts only. **To confirm by probe** from `/etc/passwd` and `/usr/lib/passwd` on the installed disk, with no shadow data recorded |
| GIS vendor configuration | `gnome-initial-setup` 51.1, built by utah-packages with `-Dparental_controls=disabled` and no fixed vendor-file path. Two files ship: `/etc/gnome-initial-setup/vendor.conf` from projectbluefin/common (`system_files/bluefin/etc/...`: `[pages] skip=software`), and `/usr/share/gnome-initial-setup/vendor.conf` from utah's GIS package (`[pages] existing_user_only=language;keyboard`). GIS 51.1 reads the `/etc` file and uses `/usr/share` only when `/etc` has none (`gis-driver.c`, `load_vendor_conf_file`); they are not merged. So the effective policy is `skip=software`. **To confirm by probe:** both files on the installed disk |
| Expected pages | Under `skip=software`: language → keyboard → network → privacy → timezone → account → password → summary. From GIS 51.1's `page_table`: welcome is shown only when language is skipped, so the first page is language (its heading cycles "Welcome!" through languages); software is skipped by vendor policy; there are no parental-controls pages (not built). Network also hides itself when already connected over wire. Probe run 43333610574 showed the language page first. **To confirm by probe:** the full ordered sequence on this disk under QEMU with user-mode networking |
| Locale and keyboard | `langpacks-en` only, so English. The installed disk's `/etc/locale.conf` and `/etc/vconsole.conf` defaults are **to confirm by probe**. The probe fixes locale and keyboard rather than relying on them |
| Expected final state | One new regular user (uid ≥ 1000) created by GIS's account and password pages, a GDM greeter login with that password, and a usable GNOME Wayland session, as `desktop-first-login-cases.md` defines. **To confirm by probe:** the new user's exact uid, primary group and supplementary groups (for example whether GIS makes the first account an administrator in `wheel`), because they depend on GIS account creation and the installed system's account policy |

Dakota, LTS, NVIDIA and other utah variants are not admitted by this record.

## Minimal fixture contract

Proposed interface, not new reusable workflow inputs:

| Boundary | Required information or behavior |
|---|---|
| Input | Admitted immutable image/disk identity, journey profile, expected screens and state checks, bounded timeouts, controlled-failure case identifier |
| Reset | Fresh disposable disk overlay and fresh writable OVMF variable-store copy for every case; immutable base never receives writes |
| Boot | Matching OVMF code/variable templates, QEMU/KVM version and machine recorded; boot the disk's supported loader with no `-kernel`, `-initrd`, `-append` or replacement loader |
| Observation | Host framebuffer checkpoints from the actual guest before a normal user exists; serial collection starts before boot |
| Input | Host-local QEMU monitor keyboard/pointer events to the native GDM/GIS surface; no stand-in UI or post-login session required to start the driver |
| Management | Separately approved diagnostic channel; read guest state and journals without authenticating the tested desktop user or completing setup |
| Output | Case verdict and last reached checkpoint, sanitized provenance, actual UI evidence and serial/journal artifacts on success and failure |
| Teardown | Stop QEMU, detach mounts/loop devices, delete writable disks, variable stores and ephemeral credentials, including on timeout |

## Shared helpers and pre-login input

Use the existing QEMU lifecycle, serial collection and
[framebuffer helper](../../../../../tests/shared/qemu_screendump.py) as starting
points. Its current fixed monitor/output paths need case isolation before
concurrent use. Add bounded monitor input and checkpoint recognition around those
helpers rather than duplicating VM orchestration. Normal-session shared helpers
may check desktop usability only after native login has completed; do not run
qecore-headless preparation where it would enable autologin.

Prefer host input for the first feasibility run because it does not depend on
discovering a pre-login accessibility bus. Fix locale, keyboard and resolution;
wait for identified screen/control checkpoints before each action. A delay or
successful input write is never evidence of a successful screen transition.
Any visual recognition must be calibrated against captured real guest frames,
including negative examples. An unrecognized screen fails at its deadline.

## Management trust boundary

The diagnostic channel is an unresolved security choice, not permission to add
a privileged account. Review a console/guest-agent channel or a narrowly scoped
ephemeral key-only management identity separately, proving it does not count as
a regular user, alter GDM/GIS selection, or change desktop authentication. Until
that proof and approval exist, journal/account assertions remain unimplemented.

## Acceptance cases and evidence

The [checkpoint, controlled-failure and evidence contract](desktop-first-login-cases.md)
defines required assertions, credential handling and retained artifacts. It also
requires repeatable hosted passing and failing runs before blocking rollout.

## Delivery and remaining approvals

1. Review this contract and select the first immutable disk/profile with its
   inspected native journey. Approve the management trust boundary and hosted
   runner capacity; this document does not spend resources or create credentials.
2. Implement the bounded monitor-input feasibility probe with shared helpers;
   prove native surface reachability and credential-safe collection on that disk.
3. Implement the applicable checkpoints and controlled failures, unit-test
   timeouts/recognition/cleanup, then retain repeatable hosted evidence.
4. Only after that evidence, propose suite/workflow interfaces and blocking
   rollout separately. Existing smoke callers retain their current contract.

Test content and reusable GitHub Actions code belong in testsuite; lab resources
belong in projectbluefin/lab. No runtime coverage box in #1026 is checked by
merging this design alone.
