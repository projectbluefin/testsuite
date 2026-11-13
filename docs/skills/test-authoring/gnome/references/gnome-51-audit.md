---
name: gnome-51-audit
description: "Audit of GNOME 50-specific workarounds against GNOME 51 — per-workaround verdict, the live gnomeos-51 run evidence, and the Calculator / Text Editor divergences found in that run."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# GNOME 50 → 51 Workaround Audit

## Purpose

Audits every GNOME 50-specific workaround in the repo against GNOME 51 and
records what a **live `gnomeos-51` run** actually proved. This is the source of
truth the `gnome` skill (`SKILL.md`) links to. `dakota:testing` runs GNOME
51.1, and its e2e smoke runs exercise workarounds on GNOME 51 (see §Run evidence).
Keep GNOME 50 workarounds while another tested image still needs them.
Version-branch or fix a workaround only after a run proves behavior diverges.

## Status key

- **works on 51** — a passing scenario exercised the workaround on GNOME 51.
  This does not establish whether the workaround is still required.
- **still required** — a targeted comparison shows the workaround is needed
  on GNOME 51.
- **broken on 51** — the run proved the workaround no longer works on GNOME 51;
  the step needs a GNOME 51 fix or a version branch.
- **obsolete** — a targeted comparison shows GNOME 51 no longer needs it.
  Keep the GNOME 50 path while any tested image needs it.
- **LIKELY-KEEP** — no run has exercised this workaround on GNOME 51. Treated as
  still required until a run says otherwise. **Do not** promote this to
  "still required" without run evidence.
- **UNVALIDATED** — pre-run placeholder. Deprecated: every row below now carries
  a verdict from the run in §Run evidence, or a `LIKELY-KEEP` note when the run
  did not exercise it.

## The twelve GNOME 50 workarounds

| # | Workaround | Status (GNOME 51) | Where |
|---|---|---|---|
| 1 | Re-prepend `global.context.unsafe_mode = true` before every `Shell.Eval` (GNOME 50 reset it) | **LIKELY-KEEP** — not exercised by the smoke-a/smoke-b run (Bluefin-only Shell.Eval reads); still required on 50, assume it holds on 51 until a run says otherwise | `tests/smoke/features/steps/steps.py`; documented in `SKILL.md` "Screen Lock/Unlock" / "Overview search entry" |
| 2 | Double-quoted `Shell.Eval` results `(true, '"true"')` | **LIKELY-KEEP** — not exercised by the run; the `clutter_text.get_text()` tuple format is unchanged upstream | `tests/smoke/features/steps/steps.py` |
| 3 | Extension `state=6` via `Shell.Eval` → use `GetExtensionInfo` D-Bus | **LIKELY-KEEP** — no extensions on plain gnomeos, so the state check is not exercised; the D-Bus method is the only public path and still required | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Extension state via D-Bus" |
| 4 | `filler`/`frame` toplevel-role fallback + require populated subtree | **WORKS ON 51** — Files, Calculator, Text Editor, and fractional/integer scale windows resolved their toplevels; the run does not prove which fallback was needed | `tests/shared/gnome_shell_steps.py`; `SKILL.md` "Window-role checks must prove the subtree is populated" |
| 5 | Nautilus sidebar role (`home_folder_is_in_the_sidebar`) | **WORKS ON 51** — `home_folder_is_in_the_sidebar` passed; necessity remains unproven | `tests/smoke/features/steps/gnome_files_steps.py` |
| 6 | Nautilus AT-SPI app-name handling (`FILES_APP_NAMES`, `_nautilus_app`) | **WORKS ON 51** — Files launched, navigated, and closed; necessity remains unproven | `tests/smoke/features/steps/gnome_files_steps.py` |
| 7 | Ptyxis window title (`user@host:~`) | **UNEXERCISED on `dakota:testing`** — [smoke-a run 43170644165](https://github.com/projectbluefin/testsuite/actions/runs/43170644165) skipped “Ptyxis terminal launches successfully” because Ptyxis is not installed. A skip does not establish whether the workaround works or is obsolete on 51; retain it for images running GNOME 50. | `tests/smoke/features/steps/gnome_apps_steps.py:34-38` |
| 8 | ScreenSaver D-Bus `Lock` (not `screenShield.lock(true)`) | **LIKELY-KEEP** — `screen_lock_engages` not in the smoke-a/smoke-b run; still required on 50 | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Screen Lock/Unlock D-Bus calls" |
| 9 | `Main.overview.visible` reads `false` in QEMU; do not assert it | **LIKELY-KEEP (unverified)** — the scenarios passed, but `overview_is_open` checks `OverviewActive`, not `Main.overview.visible`, so the pass cannot show the workaround is still needed; needs a targeted 51 probe of `Main.overview.visible` | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Activities overview (GNOME 50 QEMU)" |
| 10 | Notification banner dismissal check | **WORKS ON 51** — `toast_notification_banner_can_be_dismissed` passed; necessity remains unproven | `tests/smoke/features/steps/gnome_notifications_steps.py` |
| 11 | Panel buttons `showing=False` before overview toggle | **LIKELY-KEEP (unverified)** — panel helpers match role/name without checking `showing`, so the run does not measure this property; needs a targeted 51 probe recording `showing` | `tests/shared/gnome_shell_steps.py` |
| 12 | keyring skip on GDM restart | **LIKELY-KEEP** — GDM restart not exercised by the smoke run; still required on 50 | `tests/smoke/features/environment.py` |

Rows 4, 5, 6, and 10 worked in the run in §Run evidence; a passing scenario
does not prove that the workaround is required. Rows 9 and 11 remain
unverified because passing scenarios did not measure the affected properties.
Rows 1, 2, 3, 8, and 12 were not exercised by the plain GNOME OS
smoke run and carry `LIKELY-KEEP`. Row 7 was also skipped on `dakota:testing`
because Ptyxis was absent. **This audit is incomplete**: issue #827 still
requires evidence for the unverified rows, including targeted probes for 9 and 11.

## Run target

The image exists and is maintained upstream; `gnomeos-latest` has **not** moved
since 2026-08-07 and is not a GNOME 51 proxy — use `gnomeos-51`. The tag moves,
so pin the digest on the day you run.

```sh
gh workflow run manual.yml \
  -f image=quay.io/gnome_infrastructure/gnome-build-meta@sha256:b3cc30d8052b914c4741ae7ee35c5b1815cccc7bfb2e4e2badb141d2091bdee5 \
  -f suites=smoke \
  -f test_ref=827-gnome-51-audit \
  --repo kylerankin/testsuite
```

## Run evidence

- **Run:** https://github.com/projectbluefin/testsuite/actions/runs/42919511431
- **Image:** `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-51`
- **Image digest (pinned):** `sha256:b3cc30d8052b914c4741ae7ee35c5b1815cccc7bfb2e4e2badb141d2091bdee5`
- **testsuite commit under test:** `05e6ae5afac4bf49a3162d3c09b013264da979e8`
- **smoke-a:** 28 passed, 11 failed · **smoke-b:** 51 passed, 11 failed
- **smoke-firefox:** passed

- **`dakota:testing` PR VM run:** https://github.com/projectbluefin/testsuite/actions/runs/43170644165 — logs GNOME Shell 51.
- **`dakota:testing` v1 gate run:** https://github.com/projectbluefin/testsuite/actions/runs/43126910959 — smoke-a and smoke-b skip Calculator and Text Editor because the apps are not installed.
- **Image version:** GNOME 51.1 is recorded in [dakota #1796](https://github.com/projectbluefin/dakota/pull/1796).

The 11 failures in smoke-a and smoke-b are **Bluefin-only** (see §Bluefin-only
failures) — extensions, power-status, tailscale, fastfetch, and failed-units are
expected on plain gnomeos-51 and are **not** GNOME 51 divergences. The two
genuine divergences are the Calculator and Text Editor scenarios in §Run
findings.

## Run findings — Calculator and Text Editor divergences

These are **not** among the twelve workarounds above. In the plain `gnomeos-51`
run above, Calculator and Text Editor scenarios diverged. In the `dakota:testing`
v1 gate run above, both apps were absent and their scenarios skipped; that run
does not show them passing or failing. When the PR validation plan selects
VM-covered suites, the check runs `dakota:testing`; it cannot capture AT-SPI
trees for apps that image does not ship.
The findings below are **documented here, not fixed**.

### Calculator display lookup — broken on 51

- **Failing:** `basic_multiplication` ("display shows 42"),
  `subtracting_to_a_negative_result` ("display shows -5").
- **Passing (decoys):** `basic_addition` (3), `basic_division` (3),
  `basic_subtraction` (5), `clear_button_resets_display` (0),
  `decimal_arithmetic` (3), `calculator_launches`.
- **Root cause:** `click_calculator_button` / `Calculator display shows` in
  `tests/smoke/features/steps/gnome_calculator_steps.py` resolve the display via
  `_display_candidates()`, which walks the window for nodes with role in
  `{text, entry, label, static}` and a non-empty value. On GNOME 51 the display
  node is **not** located, so the step falls back to the keypad **buttons**
  (7, 8, 9, `×`, `÷`, `−`, `+`, `=`, …). A single positive digit that happens to
  equal a button label (`3`, `5`, `0`) matches by accident and passes; `42` and
  `-5` match no button and fail. The screenshot
  `screenshot_smoke_failed_basic_multiplication.png` shows the calculator with
  no display value matching.
- **What the run proves:** the step did not locate the display node on this
  `gnomeos-51` image. Capture the app's GNOME 51 AT-SPI tree to identify the
  real display node or distinguish it from the keypad buttons.
- **Also failing:** `calculator_closes_cleanly_via_ctrl_q` — `Ctrl+Q` did not
  quit (see Text Editor below; shared key-combo path).

### Text Editor new-document / quit — broken on 51

- **Failing:** `text_editor_creates_new_empty_document_buffer` (`Ctrl+N`),
  `text_editor_save_dialog_is_open` (`Ctrl+S`), `text_editor_discard_dialog_is_open`
  (`Ctrl+Shift+S`), and the Text Editor coredump/quited scenarios.
- **Passing:** `text_editor` `@input` ("Type text") — plain typing works.
- **Root cause:** after `Ctrl+N` the buffer still shows the previous scenario's
  content (`"Bluefin smoke testPrevious document content"`) instead of a new
  empty buffer. `Ctrl+N` is not creating a new document on GNOME 51. Plain
  character entry via uinput works, so the input layer is fine — the failure is
  specific to the `Key combo` path (`Ctrl+N`/`Ctrl+S`/`Ctrl+Shift+S`).
- **What the run shows:** the `Key combo` step did not drive the expected
  accelerator for Text Editor on this `gnomeos-51` image. A run with `qecore`
  debug logging is needed to establish whether the combo is dropped or mis-routed.

## Bluefin-only failures (expected on gnomeos-51 — not divergences)

The 11 failures in smoke-a and smoke-b are Bluefin's bundled extensions,
power-status, tailscale, fastfetch, and failed-units. These are **not** part of
this audit — plain gnomeos-51 has none of Bluefin's extensions and a different
power-management layout. Do not open GNOME 51 workarounds for them.

## Moving a LIKELY-KEEP row to confirmed

Run the targeted scenarios on gnomeos-51 via the run target above and record the
result here with the run URL. Until then, keep the GNOME 50 workaround.
