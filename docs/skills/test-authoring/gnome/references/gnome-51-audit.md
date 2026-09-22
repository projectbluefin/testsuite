---
name: gnome-51-audit
description: "Audit of GNOME 50-specific test workarounds against GNOME 51; classify each as still required / broken / obsolete once validated."
metadata:
  type: reference
  audience: agents
  maturity: experimental
---
# GNOME 50 Workaround Audit (issue #827)

This is the working inventory for issue #827. It lists every GNOME 50-specific
workaround in the repo, where it lives, and the published GNOME 51 fact that
bears on it. **The classification column is intentionally `UNVALIDATED`** — the
only way to move a row to `still required` / `broken on 51` / `obsolete` is to
run it on a `gnomeos-51` image via `manual.yml`. Do not promote a guess to a
classification.

## Governing facts (GNOME 51, from issue #827)

- GNOME 51 GA is **2026-09-16**; `gnomeos-latest` rolls to it with no signal in
  this repo.
- GNOME 51 is **Wayland-only** — the X11 session and legacy NVIDIA paths are
  dropped. Any workaround that exists to work around X11/NVIDIA is a prime
  `obsolete` candidate once confirmed on a Wayland-only 51.
- The **extension API is frozen**. Workarounds that key off the public
  extension / Shell D-Bus API are the *least* likely to break.
- Bluefin stays on **GNOME 50** until its own rebase. **Do not delete any GNOME
  50 workaround above** — version-branch only where behavior genuinely diverges,
  and only after a 51 run proves the divergence.

## Inventory

Status key: `UNVALIDATED` = must run on gnomeos-51; `LIKELY-KEEP` = published
fact suggests it survives but still must be confirmed; `LIKELY-AT-RISK` =
published fact suggests it may change.

| # | Workaround | Status | GNOME 51 context | Where |
|---|---|---|---|---|
| 1 | Re-prepend `global.context.unsafe_mode = true` before every `Shell.Eval` ("GNOME 50 resets it") | UNVALIDATED / LIKELY-KEEP | `Shell.Eval` is frozen; the *reset-after-ui* behavior is a 50 quirk, not an API contract. Keep the guard until a 51 run shows 51 does not reset. | `tests/shared/gnome_shell_steps.py:31,36,298,332`; `tests/smoke/features/steps/steps.py:99-108` |
| 2 | Double-quoted `Shell.Eval` results `(true, '"true"')` | UNVALIDATED / LIKELY-KEEP | gdbus tuple formatting is unchanged by the Wayland rebase. Low risk, but confirm the quoting on 51. | `tests/smoke/features/steps/steps.py:128-135`; `tests/bazzite/features/steps/steps.py:40` |
| 3 | Extension `state=6` via `Shell.Eval` → switch to `GetExtensionInfo` D-Bus | UNVALIDATED / LIKELY-KEEP | `org.gnome.Shell.Extensions` is part of the frozen extension API; the transient `state=6` (INITIALIZED) path is expected to persist. Keep `GetExtensionInfo`. | `docs/skills/test-authoring/gnome/SKILL.md` (Extension state via D-Bus); bazzite steps |
| 4 | `filler` toplevel-role fallback (accept `{"frame","filler"}`, require populated subtree) | UNVALIDATED / AT-RISK | AT-SPI role names are not frozen and GNOME has retitled AT-SPI roles before. Confirm `filler` is still emitted on 51; if it changed, broaden the accepted set rather than dropping the false-pass guard. | `tests/smoke/features/steps/firefox_steps.py:46-47`; `gnome/SKILL.md` Window-role checks |
| 5 | Nautilus sidebar "list item" → "button" role | UNVALIDATED / AT-RISK | Nautilus ships independently of the shell; its bundled version in 51 may rename the role again. Re-audit the role on 51. | `tests/smoke/features/steps/gnome_files_steps.py:137,155` |
| 6 | Nautilus AT-SPI app-name handling | UNVALIDATED / AT-RISK | App-name is set by Nautilus, not the shell. Re-check the expected app-name against the 51-bundled Nautilus. | `tests/smoke/features/environment.py:235` |
| 7 | Ptyxis window title `"Ptyxis"` → `"Terminal"` | UNVALIDATED / AT-RISK | Ptyxis releases on its own cadence; the 51-bundled title string may differ. Re-confirm on 51. | `tests/smoke/features/steps/gnome_apps_steps.py:35` |
| 8 | ScreenSaver D-Bus `Lock` (instead of deprecated `Shell.Eval` `Main.screenShield.lock`) | UNVALIDATED / LIKELY-KEEP | `org.gnome.ScreenSaver` is a stable public D-Bus interface; the `Shell.Eval` lock path stays deprecated. Keep the D-Bus lock. | `gnome/SKILL.md` Screen Lock/Unlock D-Bus calls |
| 9 | `Main.overview.visible` is `false` in QEMU → quarantine until live 50/QEMU confirm | UNVALIDATED / AT-RISK | This is a QEMU/compositor artifact, not an X11-vs-Wayland thing, but the 51 compositor is new. Re-prove on 51 QEMU before changing the quarantine. | `gnome/SKILL.md` Overview search / Activities overview (GNOME 50 QEMU); smoke steps 541, 645 |
| 10 | Notification banner API usage | UNVALIDATED / LIKELY-KEEP | `org.freedesktop.Notifications` is a freedesktop standard, frozen. Low risk; confirm on 51. | `tests/smoke/features/steps/gnome_notifications_steps.py:104` |
| 11 | Panel buttons `showing=False` / `INT_MIN` positions → match by role, not coordinate | UNVALIDATED / AT-RISK | "Wayland reports `showing=False` for all panel buttons" is exactly the kind of Wayland-specific AT-SPI artifact the rebase may or may not reproduce. This is the highest-value row to validate first. | `tests/shared/gnome_shell_steps.py:200,231,272`; `gnome_shell.feature:72` |
| 12 | keyring skip on GDM restart (5× `environment.py`) | UNVALIDATED / LIKELY-KEEP | GDM restart churn is unchanged by the rebase; the keyring skip guards the same bus-socket churn. Likely still required; confirm. | 5× `environment.py` files |

## How to validate each row

1. Build/run a pre-flip `gnomeos-51` image (`quay.io/gnome_infrastructure/gnome-build-meta`,
   tag `51.rc` / `51.0`) through the repo's `manual.yml` manual-run workflow.
   *No image or workflow target is available in this environment* — this step is
   lab infra, not testsuite.
2. Run the `smoke`, `bazzite`, `vanilla-gnome` and `software` suites against it.
   The `software` suite's own `@future` rows are a separate inventory — see
   [gnome-51-software-revalidation.md](gnome-51-software-revalidation.md); a
   `software` run on gnomeos skips them, so it cannot validate them.
3. For each row, move the status to one of:
   - `still required` — 51 still shows the 50 behavior; keep the workaround.
   - `broken on 51` — 51 no longer shows it and the test now fails; fix the step.
   - `obsolete` — 51 no longer needs it and the test still passes; keep only if
     Bluefin (50) still does.
4. Version-branch (never delete) where behavior genuinely diverges, so Bluefin
   on 50 keeps working. See `docs/skills/test-authoring/behave/SKILL.md` for
   version-conditional step patterns.

## Coordination

- **Do not claim qecore GNOME 51 support** until PR #821 (qecore pins, runner
  4.16 → 4.19.3) lands. GNOME 50 needed qecore ≥ 4.12; 51 needs the pinned
  4.19.3.
- The `software` suite's `@future` GNOME Software rows are inventoried
  separately in
  [gnome-51-software-revalidation.md](gnome-51-software-revalidation.md)
  (issue #847), including why a `software` run cannot validate them.
- The `vanilla-gnome` suite already carries an informational `ShellVersion`
  canary — the `GNOME Shell version is reported` step inside the `@gnome_core`
  "GNOME Shell process is running and accessible via AT-SPI" scenario in
  `gnome_core.feature` (landed in #864). It prints the running Shell version so
  the flip is visible before it reads as a regression, and it warns rather than
  raises on every failure path, so it cannot gate the run. See
  `docs/skills/ci-ops/ops/references/fedora-version-targets.md`.
