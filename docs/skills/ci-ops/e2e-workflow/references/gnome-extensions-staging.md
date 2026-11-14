---
name: gnome-extensions-staging
description: "Build a hive extension from its pinned revision and stage it into the isolated GNOME OS guest before GNOME Shell starts (#909)"
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Staging candidate extensions on GNOME OS (#909)

Companion to [gnome-extensions-validation.md](gnome-extensions-validation.md), which covers the
guest, the isolated session and the service gate.

`gnomeos-extensions.yml` (dispatch-only, `extension` = a collection profile) has two jobs:

1. **Package**: `scripts/extension_candidates.py plan` reads the profile's repository and
   `package_command` from `tests/extensions/collection.json` and the revision from the canonical
   contract (one pin). It checks out that revision, runs the candidate's own recipe in the
   GNOME OS development image with `--network=none` twice, from two copies seconds apart,
   and `compare`s the ZIPs. `validate` checks the first against its contract. Only the ZIP
   and `build-provenance.json` (builder digest, revision, recipe, reproducibility, validation)
   leave the job.
2. **Validate**: builds the [harness overlay](gnomeos-desktop-canary.md) and calls `gnome-e2e`
   with `suite: extensions` and `extension-artifacts: extension-candidate`.

The action's `extension-artifacts` input (a directory of ZIPs; `suite: extensions` only) does
the rest:

| When | What | Where |
|------|------|-------|
| Before boot, disk mounted | `extension_candidates.py stage`, as root on the runner, validates each ZIP and extracts its regular files into a new `<uuid>/` | `/var/home/bluefin-test/.local/share/gnome-shell/extensions/` |
| After boot, first session | `glib-compile-schemas --strict` with the guest's GLib, as `bluefin-test` (what `gnome-extensions install` does) | `<uuid>/schemas` |
| After the GDM restart | `gnome-extensions info <uuid>` as `bluefin-test` | `results/candidate-discovery.txt` |
| Behave | `--tags` = the staged profiles' collection tags | `results/results.json` |
| Gate | `extension_validation.py --require-tag <tag>`: every scenario with the tag passed, at least one exists | step log |

Why the user's directory, not `/usr/share/gnome-shell/extensions` or the overlay image:

- Only the desktop session loads it. The harness account never runs a Shell, and the
  isolation report is unchanged by staging.
- The helper fault-injection scenarios (SJC Gold, Stock Market) replace files inside the
  installed package, which needs a directory the desktop user owns.
- The overlay stays candidate-free and reusable; each run stages its own candidate, which is
  what a fresh guest per extension needs.

`stage` refuses a symlink anywhere from `.local` down, never merges into an existing `<uuid>/`,
creates files with `O_EXCL|O_NOFOLLOW`, caps the expanded size at 64 MiB and writes
`results/candidate-provenance.json` (contract identity plus the actual ZIP SHA256). The
candidate is never enabled by the harness: the scenarios enable it.

**Pins**: the source revision is pinned in `CANONICAL_CONTRACTS`. `zip_sha256` is not:
`gnome-extensions pack` writes each member's file time, and it copies schemas and builds
`locale/` in a fresh temporary directory, so two builds of one revision differ in bytes but
not in content (run 43606155009: `byte_identical: false`, `content_identical: true`). A
hash pinned today would reject the next honest rebuild. Pin `zip_sha256` only once a builder
publishes one immutable ZIP per revision, or the recipe normalizes file times.

## Gotchas

- `gnome-extensions pack --extra-source=data/x` stores the file as `x` at the archive root
  (it keys extras by basename). Just Perfection's `resources.gresource` is therefore at the
  root, where `lib/Prefs/Prefs.js` loads it; the contract once required
  `data/resources.gresource` and rejected the real build.
- `pack` ships only `schemas/*.gschema.xml`, never `gschemas.compiled`; `gnome-extensions
  install` compiles them. Staging by extraction must compile them too (above), and a
  contract that requires `schemas/gschemas.compiled` must be checked against a real build.
- The Shell's preferences service (`js/dbusServices/extensions/main.js`) has no
  `Gtk.Application`, so `gnome-extensions prefs` windows have no GTK application id. Find
  them by Mutter's WM class (the Wayland app id `org.gnome.Shell.Extensions`); the
  lifecycle step's filter on `get_gtk_application_id()` alone never matched (run 43606969251).
- Stopping GDM for the test login can time out and SIGKILL the first Shell. Its `OnFailure=`
  unit `org.gnome.Shell-disable-extensions.service` then sets `disable-user-extensions true`,
  and every enable in the test login silently fails (run 43609183896; run 43606969251 missed
  the race). With candidates staged, the action sets it back to `false` after the restart and
  records the value in `results/candidate-discovery.txt`. The Shell watches that key, so no
  second restart is needed.
