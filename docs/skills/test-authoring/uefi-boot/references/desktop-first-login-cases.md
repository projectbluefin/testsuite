---
name: desktop-first-login-cases
description: "Load when implementing or reviewing desktop first-login checkpoints, failure cases and retained evidence."
metadata:
  type: reference
  audience: agents
  maturity: draft
---

# Desktop first-login acceptance cases and evidence

These are proposed acceptance cases for the
[desktop qualification contract](desktop-first-login.md), not existing runtime
coverage. Apply them only to an admitted image and journey profile.

## Qualification state machine

Every transition has a finite deadline recorded in the profile. Missing evidence,
unknown profile, premature desktop arrival and collection failure fail the case.

| Checkpoint | Evidence and assertions |
|---|---|
| Fresh disk | Compare preparation manifest; GIS profiles have no regular user or completion stamp; no display-manager autologin override |
| Firmware and loader | Record launch arguments, firmware hashes, ESP/loader provenance and boot progress; guest confirms EFI boot and expected deployment; EFI presence alone does not identify the loader |
| Native first-use surface | Capture real greeter/GIS frame; verify expected profile and ordered required screens; no debug-forced wizard |
| Account setup, when applicable | Real input creates the account and chosen settings through native GIS; independent state checks verify the new non-root account, locale/keyboard/privacy choices and completion state |
| Authentication | Submit credentials at native GDM; for automatic GIS-to-desktop handoff, first verify that handoff, then log out and test native GDM login explicitly |
| User desktop | Verify active graphical session belongs to the expected UID, capture desktop, and launch/interact with a basic application using existing desktop helpers |

For no-OOBE profiles, verify credentials were provisioned through the admitted
route, then exercise native greeter authentication. Report account creation as
`not-applicable` with the profile's reason; it must never be counted as passed.

## Controlled failures and repeatability

Each row starts from a fresh disk and variable store. Controlled failures must
produce a failed qualification verdict at the named checkpoint; an experiment
wrapper may confirm that expected failure without publishing a passing desktop
qualification result.

| Case | Required outcome |
|---|---|
| Supported happy path | All applicable checkpoints pass with matching UI and independent state evidence |
| Wrong password | Native greeter rejects it, no authenticated session appears, authentication checkpoint fails; no fallback credentials |
| Broken loader handoff | On a disposable copy, prevent the selected loader from loading; boot checkpoint fails even if diagnostic management is reachable |
| Missing required setup screen | Omit or make one expected transition unreachable in a controlled fixture; required-screen checkpoint fails, even if a desktop later appears |
| Failed GIS session handoff | Prevent the created user's graphical session from becoming usable; account existence alone cannot pass desktop checkpoint |
| Missing evidence | Withhold a required screenshot/journal/provenance artifact; evidence collection fails qualification |

Demonstrate at least three consecutive hosted happy-path runs for each admitted
profile plus hosted controlled failures. Retain run URLs, image/firmware hashes,
checkpoint timing and observed flake rate before proposing a blocking rollout.
Unit tests or static configuration checks do not satisfy hosted execution proof.

## Credentials and retained evidence

Generate credentials per case in runner memory. Never accept repository secrets
for desktop login. Suppress shell tracing, command echo and monitor input logs
while entering credentials; do not pass passwords in process arguments or saved
configuration. Use artificial account names, never real personal identities.

Capture only approved non-secret checkpoints. Do not publish password-entry or
account-detail frames, continuous video, raw input transcripts, disk overlays,
shadow files, keys or credential hashes. On failures in sensitive screens,
publish the last safe frame plus a sanitized failure reason. Stage a sanitized
artifact allowlist before upload; inspect serial/journal content for credential
exposure and fail collection rather than publishing unsafe raw material.

Retain firmware package/version and hashes, disk/image identity, preparation
manifest, QEMU invocation without secrets, boot/session identifiers, checkpoint
verdicts/times, safe UI frames and sanitized serial/journal for both outcomes.
Use a proposed seven-day diagnostic retention window, subject to fixture review.
