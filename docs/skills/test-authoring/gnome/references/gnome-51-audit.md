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
truth the `gnome` skill (`SKILL.md`) links to. Do **not** delete GNOME 50
workarounds — Bluefin stays on GNOME 50. Version-branch (or fix) a workaround
**only** after a 51 run proves the behavior genuinely diverged.

## Status key

- **still required** — the workaround's behavior holds on GNOME 51; the run
  confirmed it. Keep it (Bluefin needs it; GNOME 51 needs it).
- **broken on 51** — the run proved the workaround no longer works on GNOME 51;
  the step needs a GNOME 51 fix or a version branch.
- **obsolete** — the workaround targets a GNOME 50 bug that no longer exists on
  51. (None found yet.)
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
| 4 | `filler`/`frame` toplevel-role fallback + require populated subtree | **STILL REQUIRED** — run confirmed: Files, Calculator, Text Editor, and fractional/integer scale windows all resolved their toplevels on 51 | `tests/shared/gnome_shell_steps.py`; `SKILL.md` "Window-role checks must prove the subtree is populated" |
| 5 | Nautilus sidebar role (`home_folder_is_in_the_sidebar`) | **STILL REQUIRED** — run confirmed: `home_folder_is_in_the_sidebar` passed on 51 | `tests/smoke/features/steps/gnome_files_steps.py` |
| 6 | Nautilus AT-SPI app-name handling (`FILES_APP_NAMES`, `_nautilus_app`) | **STILL REQUIRED** — run confirmed: Files launched, navigated, and closed cleanly on 51 | `tests/smoke/features/steps/gnome_files_steps.py` |
| 7 | Ptyxis window title (`user@host:~`) | **LIKELY-KEEP** — Ptyxis not exercised by the smoke run; still required on 50 | `tests/smoke/features/steps/gnome_apps_steps.py` |
| 8 | ScreenSaver D-Bus `Lock` (not `screenShield.lock(true)`) | **LIKELY-KEEP** — `screen_lock_engages` not in the smoke-a/smoke-b run; still required on 50 | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Screen Lock/Unlock D-Bus calls" |
| 9 | `Main.overview.visible` reads `false` in QEMU; do not assert it | **STILL REQUIRED** — run confirmed: `super_key`, `typing_in_overview`, `switching_workspace` all passed on 51 | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Activities overview (GNOME 50 QEMU)" |
| 10 | Notification banner dismissal check | **STILL REQUIRED** — run confirmed: `toast_notification_banner_can_be_dismissed` passed on 51 | `tests/smoke/features/steps/gnome_notifications_steps.py` |
| 11 | Panel buttons `showing=False` before overview toggle | **STILL REQUIRED** — run confirmed: Activities / clock / system-menu toggle buttons were visible on 51 | `tests/shared/gnome_shell_steps.py` |
| 12 | keyring skip on GDM restart | **LIKELY-KEEP** — GDM restart not exercised by the smoke run; still required on 50 | `tests/smoke/features/environment.py` |

Rows 4–11 are **confirmed** by the run in §Run evidence. Rows 1, 2, 3, 7, 8, 12
were **not** exercised by the smoke-a/smoke-b run (they are Bluefin-only or
bazzite-only paths), so they carry `LIKELY-KEEP`. Before calling this audit
complete, either run those paths on gnomeos-51 or note in the PR that they
remain unverified.

## Run target

The image exists and is maintained upstream; `gnomeos-latest` has **not** moved
since 2026-08-07 and is not a GNOME 51 proxy — use `gnomeos-51`. The tag moves,
so pin the digest on the day you run.

```yaml
# .github/workflows/manual.yml  — run this to produce the evidence below
name: Manual GNOME 51 run
on: workflow_dispatch
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run smoke suite on gnomeos-51
        uses: projectbluefin/actions/e2e-run@main
        with:
          image: quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-51
          suites: smoke-a,smoke-b
```

## Run evidence

- **Run:** https://github.com/projectbluefin/testsuite/actions/runs/42919511431
- **Image:** `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-51`
- **Image digest (pinned):** `sha256:b3cc30d8052b914c4741ae7ee35c5b1815cccc7bfb2e4e2badb141d2091bdee5`
- **testsuite commit under test:** `05e6ae5afac4bf49a3162d3c09b013264da979e8`
- **smoke-a:** 28 passed, 11 failed · **smoke-b:** 51 passed, 11 failed
- **smoke-firefox:** passed

The 11 failures in smoke-a and smoke-b are **Bluefin-only** (see §Bluefin-only
failures) — extensions, power-status, tailscale, fastfetch, and failed-units are
expected on plain gnomeos-51 and are **not** GNOME 51 divergences. The two
genuine divergences are the Calculator and Text Editor scenarios in §Run
findings.

## Run findings — Calculator and Text Editor divergences

These are **not** among the twelve workarounds above. They are vanilla GNOME
app smoke scenarios that the maintainer flagged ("look at calculator and text
editor"). Both fail on GNOME 51 and pass on GNOME 50 (Bluefin). They are
**documented here, not fixed** — the fix requires the GNOME 51 AT-SPI tree for
each app, which cannot be captured locally (no VM here, `qecore` not
importable). Do not treat the notes below as fixes.

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
- **What the run proves:** the display node's role/structure on GNOME 51 differs
  from GNOME 50. The step must be re-grounded against the GNOME 51 AT-SPI tree
  for `gnome-calculator` (find the real display node, or distinguish it from the
  keypad buttons). **Not fixable from here** — capture the GNOME 51 AT-SPI tree
  first.
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
- **What the run proves:** the `Key combo` step (in `qecore`, external to this
  repo) does not drive the expected accelerator on GNOME 51 for Text Editor. The
  fix lives either in `qecore`'s key delivery or in a GNOME 51 test branch that
  avoids the broken combo. **Not fixable from here** — needs a GNOME 51 run with
  `qecore` debug logging to confirm whether the combo is dropped or mis-routed.

## Bluefin-only failures (expected on gnomeos-51 — not divergences)

The 11 failures in smoke-a and smoke-b are Bluefin's bundled extensions,
power-status, tailscale, fastfetch, and failed-units. These are **not** part of
this audit — plain gnomeos-51 has none of Bluefin's extensions and a different
power-management layout. Do not open GNOME 51 workarounds for them.

## Moving a LIKELY-KEEP row to confirmed

Run the targeted scenarios on gnomeos-51 via the run target above and record the
result here with the run URL. Until then, keep the GNOME 50 workaround.
