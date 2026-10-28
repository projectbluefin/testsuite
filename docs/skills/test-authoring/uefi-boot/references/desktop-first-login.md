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
