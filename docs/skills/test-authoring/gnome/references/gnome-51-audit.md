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
fact suggests it survives but still must be confirmed; `AT-RISK` = published
fact suggests it may change.

The **Where** column names the file and the function, constant or section that
carries the workaround, not a line number. The line numbers this table first
shipped with had drifted by more than 240 lines within six weeks, and several
rows listed only one of the places the same workaround lives. When you
version-branch a row, change every site listed for it.

| # | Workaround | Status | GNOME 51 context | Where |
|---|---|---|---|---|
| 1 | Re-prepend `global.context.unsafe_mode = true` before every `Shell.Eval` ("GNOME 50 resets it") | UNVALIDATED / LIKELY-KEEP | `Shell.Eval` is frozen; the *reset-after-ui* behavior is a 50 quirk, not an API contract. Keep the guard until a 51 run shows 51 does not reset. | `tests/shared/gnome_shell_steps.py`: `_shell_eval`, `open_quick_settings_eval`, `open_date_menu_eval`; `tests/smoke/features/steps/steps.py`: `_shell_eval`; `tests/smoke/features/steps/power_status_color_steps.py`: `_shell_eval`; `tests/smoke/features/steps/gnome_apps_steps.py`: `_shell_eval_force_close`; `tests/bazzite/features/steps/steps.py`: `logo_menu_button_present`, `activities_button_absent`; `tests/shared/extension_session.py`: `ExtensionSession.shell_json`; `tests/shared/wait_for_shell.py`: `_shell_eval_ready` |
| 2 | Double-quoted `Shell.Eval` results `(true, '"true"')` | UNVALIDATED / LIKELY-KEEP | gdbus tuple formatting is unchanged by the Wayland rebase. Low risk, but confirm the quoting on 51. | `tests/smoke/features/steps/steps.py`: `_eval_bool`; `tests/bazzite/features/steps/steps.py`: `_eval_bool`; `tests/vanilla-gnome/features/steps/steps.py`: `_shell_eval_value` |
| 3 | Extension `state=6` via `Shell.Eval` → switch to `GetExtensionInfo` D-Bus | UNVALIDATED / LIKELY-KEEP | `org.gnome.Shell.Extensions` is part of the frozen extension API; the transient `state=6` (INITIALIZED) path is expected to persist. Keep `GetExtensionInfo`. | `tests/bazzite/features/steps/steps.py`: `_extension_state`, `extension_is_enabled`; `tests/smoke/features/steps/gnome_extensions_steps.py`: `_extension_state`, `gnome_extension_is_enabled`; `gnome/SKILL.md` "Extension state via D-Bus (bazzite / GNOME 50)" |
| 4 | `filler` toplevel-role fallback (accept `{"frame","filler"}`, require populated subtree) | UNVALIDATED / AT-RISK | AT-SPI role names are not frozen and GNOME has retitled AT-SPI roles before. Confirm `filler` is still emitted on 51; if it changed, broaden the accepted set rather than dropping the false-pass guard. | `tests/smoke/features/steps/firefox_steps.py`: `FIREFOX_WINDOW_ROLES`, `_firefox_window`; the same `{"frame", "filler"}` set in smoke `gnome_apps_steps.py` (`FRAME_ROLES`), `gnome_files_steps.py`, `gnome_settings_steps.py`, `gnome_calculator_steps.py`, `gnome_text_editor_steps.py` and `tests/software/features/steps/steps.py` (`FRAME_ROLES`); wider role sets that include `filler` in smoke `gnome_extensions_steps.py` (`EXTENSIONS_WINDOW_ROLES`) and `tests/developer/features/steps/steps.py`; `gnome/SKILL.md` "Window-role checks must prove the subtree is populated" |
| 5 | Nautilus sidebar "list item" → "button" role | UNVALIDATED / AT-RISK | Nautilus ships independently of the shell; its bundled version in 51 may rename the role again. Re-audit the role on 51. | `tests/smoke/features/steps/gnome_files_steps.py`: `home_folder_is_in_the_sidebar`, `navigate_to_in_files_sidebar` |
| 6 | Nautilus AT-SPI app-name handling | UNVALIDATED / AT-RISK | App-name is set by Nautilus, not the shell. Re-check the expected app-name against the 51-bundled Nautilus. | `tests/smoke/features/environment.py`: `before_all` → `_nautilus_aliased_application`; `tests/smoke/features/steps/gnome_apps_steps.py`: `FILES_APP_NAMES` |
| 7 | Ptyxis window title `"Ptyxis"` → `"Terminal"` (now: accept any title, including bash-prompt titles) | UNVALIDATED / AT-RISK | Ptyxis releases on its own cadence; the 51-bundled title string may differ. Re-confirm on 51. | `tests/smoke/features/steps/gnome_apps_steps.py`: `PTYXIS_WINDOW_NAMES` and the comment above it |
| 8 | ScreenSaver D-Bus `Lock` (instead of deprecated `Shell.Eval` `Main.screenShield.lock`) | UNVALIDATED / LIKELY-KEEP | `org.gnome.ScreenSaver` is a stable public D-Bus interface; the `Shell.Eval` lock path stays deprecated. Keep the D-Bus lock. No test step calls it today — the `@lock_screen` scenario locks through `loginctl` — so a suite run cannot validate this row; check it by hand on the 51 VM. | `gnome/SKILL.md` "Screen Lock/Unlock D-Bus calls (GNOME 50)" (documentation only) |
| 9 | `Main.overview.visible` reads `false` in headless QEMU even with the overview open → read and set the `org.gnome.Shell` `OverviewActive` D-Bus property instead | UNVALIDATED / AT-RISK | This is a QEMU/compositor artifact, not an X11-vs-Wayland thing, but the 51 compositor is new. Re-prove on 51 QEMU before going back to `Main.overview.visible`. The bazzite suite still reads `Main.overview.visible`, so a bazzite run on 50 is the control. | `tests/smoke/features/steps/steps.py`: `_overview_active`, `_set_overview_active`, `_wait_overview_active`, `overview_is_open`; related overview-search quirks in the same file: `type_in_overview_search_entry` (entry lacks focus), `_node_text_value` (typed text lands on a child node); control: `tests/bazzite/features/steps/steps.py`: `overview_is_open` |
| 10 | Notification banner dismissal check accepts either a null `_banner` or a hidden banner | UNVALIDATED / AT-RISK | Sending uses `org.freedesktop.Notifications`, which is frozen, but the dismissal check reads `Main.messageTray._banner` — a private Shell field outside the frozen extension API. Confirm the field still exists on 51. | `tests/smoke/features/steps/gnome_notifications_steps.py`: `notification_banner_no_longer_showing` |
| 11 | Panel buttons `showing=False` / `INT_MIN` positions → match by role, not coordinate | UNVALIDATED / AT-RISK | "Wayland reports `showing=False` for all panel buttons" is exactly the kind of Wayland-specific AT-SPI artifact the rebase may or may not reproduce. This is the highest-value row to validate first. | `tests/shared/gnome_shell_steps.py`: `clock_toggle_visible`, `system_menu_toggle_visible`, `activities_toggle_in_panel`; `tests/smoke/features/gnome_shell.feature`: the `INT_MIN` note opening the Quick Settings section |
| 12 | keyring skip on GDM restart (`context.sandbox.set_keyring = False`) | UNVALIDATED / LIKELY-KEEP | GDM restart churn is unchanged by the rebase; the keyring skip guards the same bus-socket churn. Likely still required; confirm. | `before_all` in six `environment.py` files: `tests/{smoke,vanilla-gnome,software,bazzite,developer,dx}/features/environment.py` |

### GNOME 50 sites outside the twelve rows

The twelve rows are the workarounds issue #827 named. The suites carry more
GNOME 50-specific comments than that (62 across 19 files on 2026-11-09, unit
tests excluded). Before calling the audit complete, list them and check each
either maps to a row above or is noted in the run evidence:

```bash
grep -rn "GNOME 50" tests --include=*.py --include=*.feature | grep -v '^tests/unit/'
```

## How to validate each row

1. Run the published `gnomeos-51` image through the repo's `manual.yml`
   manual-run workflow (see [Run target](#run-target) below). This does **not**
   need `projectbluefin/lab`: `manual.yml` calls `e2e.yml`, whose jobs all run on
   GitHub-hosted `ubuntu-latest`.
2. Run the `smoke`, `vanilla-gnome` and `software` suites against it (`bazzite`
   only exercises Bazzite-specific extensions; row 2's bazzite anchor needs a
   Bazzite image, not gnomeos).
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

## Run target

The image exists and is maintained upstream. As of 2026-11-09,
`quay.io/gnome_infrastructure/gnome-build-meta` publishes `gnomeos-51`
(last push 2026-10-27), while `gnomeos-latest` has **not** moved since
2026-08-07 — so `gnomeos-latest` is not a GNOME 51 proxy. The tag moves, so
look the digest up again on the day you run and pin it so the evidence is
reproducible:

```bash
skopeo inspect docker://quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-51 \
  | jq -r '.Digest'
# Without skopeo, the quay tag API reports the tag's manifest digest
# (2026-10-27: sha256:0dd62dee4411ca9c119b82ac51ab75d82ad6c0f4ca6761190082d57b44af2a0d):
# curl -s 'https://quay.io/api/v1/repository/gnome_infrastructure/gnome-build-meta/tag/?specificTag=gnomeos-51&onlyActiveTags=true' \
#   | jq -r '.tags[0].manifest_digest'

gh workflow run manual.yml --repo projectbluefin/testsuite --ref main \
  -f image=quay.io/gnome_infrastructure/gnome-build-meta@sha256:<digest> \
  -f suites=smoke,vanilla-gnome,software
```

Dispatching on `projectbluefin/testsuite` needs write access. A contributor
can dispatch the same workflow on their fork (`manual.yml` passes
`test_repository: github.repository`), but only after Actions workflows are
enabled once in the fork's **Actions** tab — GitHub does not register a fork's
workflows until then, and the REST API cannot do that step (`gh workflow run`
returns `HTTP 404: workflow manual.yml not found`).

Record the run URL and image digest next to each row when moving it out of
`UNVALIDATED`.

Do not read the GNOME version off the job names: `e2e.yml` labels every
non-KDE job `GNOME 50 — <suite>` whatever image it boots, so a gnomeos-51 run
still shows "GNOME 50" in the Actions UI. Confirm the version from the
`vanilla-gnome` `ShellVersion` canary output in the run log instead (see
[Coordination](#coordination)). As of 2026-11-09 none of the `manual.yml` runs
on `projectbluefin/testsuite` since this run target was documented (2026-10-29)
have been recorded against this inventory, so every row is still `UNVALIDATED`.

## Coordination

- qecore GNOME 51 support: PR #821 (qecore pins, runner 4.16 → 4.19.3) landed
  on 2026-09-22. GNOME 50 needed qecore ≥ 4.12; 51 needs the pinned 4.19.3.
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
