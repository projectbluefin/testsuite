---
name: gnome-extensions-staging
description: "Deep dive: building, staging and gating one candidate extension in a fresh GNOME OS guest (#909)"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Staging a candidate extension (#909)

Companion to [gnome-extensions-validation.md](gnome-extensions-validation.md), which covers
the guest, the isolated session and the service gate. This page covers how one exact
extension package gets into that guest and how its run is judged.

> **One green run so far:** Just Perfection on GNOME OS `nightly.20261114.0` (Shell 51.1),
> run 43612114661: all 7 `@just_perfection` scenarios passed, 11/11 isolation checks. It is
> the only profile offered. The network widgets (SJC Gold, Stock Market) wait for the HTTPS
> fixtures #909 describes; Shade is not offered until someone runs it.

## Flow (`.github/workflows/extension-validation.yml`, manual only)

1. **Harness** — `scripts/build-gnomeos-harness.sh` builds the overlay from the nightly
   runtime and devel digests and records both in `results/harness-provenance.json`.
2. **Build** — `scripts/build_extension_artifact.py <profile> extension-artifact
   --builder-image <devel digest>` fetches the revision the canonical contract pins
   (`tests/shared/gnome_extensions_artifacts.py`), checks `HEAD` is that commit, and runs
   the collection's recipe (`package_command`, else `gnome-extensions pack .` plus
   `package_sources`) in the **same devel build** with `--network=none` and only the source
   mounted. It records the ZIP's SHA256 and the builder digest in `build-provenance.json`.
3. **Stage** — `gnome-e2e` with `suite: extensions`, `extension-zip` and `extension-sha256`.
   Before boot, `scripts/stage_extension.py` (as root, on the mounted disk) checks the hash,
   resolves the contract from the archive's own UUID, runs the member/metadata/required-path
   checks, then writes the members into
   `/var/home/bluefin-test/.local/share/gnome-shell/extensions/<uuid>/`, owned by the desktop
   user. Report: `results/extension-staging.json`.
4. **Schemas and version** — after boot, the desktop user runs `glib-compile-schemas` on the
   staged `schemas/` (what `gnome-extensions install` would have done), and the harness
   records `gnome-shell --version` in `results/guest-shell-version.txt`. Then the action's
   GDM restart starts the session that loads the extension.
5. **Run and gate** — behave runs with `--tags @<collection tag>`; the gate runs
   `extension_validation.py --require-tag <tag>`.

## What fails, and as what

| Failure                                                                                                                             | Where                     | Category    |
| ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ----------- |
| No ZIP, malformed or missing builder hash, desktop home missing, target already present, symlink in the path, no collection profile | staging                   | `harness`   |
| Archive names a UUID with no contract, or unreadable metadata                                                                       | staging                   | `metadata`  |
| Hash mismatch, unsafe member, missing required path                                                                                 | staging                   | `artifact`  |
| Schema compile or Shell version read fails                                                                                          | Install Python test stack | step error  |
| Any scenario carrying the tag not `passed` (skipped and quarantined included), or none carry it                                     | gate                      | gate reason |

A refused ZIP fails the install step after the disk is unmounted, so nothing boots and no
scenario can be blamed on an extension that was never installed. `suite: extensions`
without a staged extension also fails the gate.

## Why these choices

- **Hash from the builder, not the contract.** `gnome-extensions pack` writes timestamps, so
  the ZIP is not byte-reproducible and `zip_sha256` stays unpinned in the contracts. The
  staging step pins the contract to the hash this run's builder recorded, so the archive
  tested is the archive built.
- **Same job, offline container.** A separate build job would need a new third-party
  artifact action. The workflow uses no secrets, and the recipe runs with no network.
- **Tag inventory from `results.json`.** Behave keeps deselected scenarios in the JSON as
  `skipped`, so every scenario the tag covers is listed there; each must be `passed`.
  Feature tags count (Just Perfection tags its whole feature), as do Examples tags (the
  lifecycle outline tags each profile's row).

## Failures real GNOME OS runs found

| Symptom                                                                                            | Cause                                                                                                                                                       | Fix                                                                                                                                  |
| -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Staging refused the real ZIP: `missing required paths: data/resources.gresource` (run 43606155009) | `gnome-extensions pack --extra-source=data/x` stores `x` at the archive root; `lib/Prefs/Prefs.js` loads `${path}/resources.gresource`                      | Contract requires `resources.gresource`                                                                                              |
| `No accessible preferences window`, the other 6 passed (run 43606969251)                           | The Shell's prefs service has no `Gtk.Application`, so its windows have no GTK application id                                                               | Match Mutter's WM class (Wayland app id `org.gnome.Shell.Extensions`) too                                                            |
| Every scenario: `did not become enabled` (run 43609183896)                                         | Stopping GDM timed out and SIGKILLed the first Shell; its `OnFailure=` unit `org.gnome.Shell-disable-extensions.service` set `disable-user-extensions true` | After the restart the action sets it back to `false` (the Shell watches the key) and records it in `results/extension-discovery.txt` |

The third is a race: run 43606969251 and the green run missed it. Rebuilds are not
byte-identical (run 43606155009: same members and CRCs, different bytes), which is why the
hash comes from this run's builder rather than the contract.

## Run it

```bash
gh workflow run extension-validation.yml -R projectbluefin/testsuite --ref main \
  -f profile=just-perfection
```

Artifact `extension-validation-<profile>` holds `results/` (scenario JSON, staging, build and
harness provenance, guest Shell version, journal), the ZIP and `session-isolation.json`.
