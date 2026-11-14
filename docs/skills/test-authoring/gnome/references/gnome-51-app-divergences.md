---
name: gnome-51-app-divergences
description: "Calculator display lookup and Text Editor new-document/quit failures found in the plain gnomeos-51 run; documented, not fixed. Not among the twelve audited GNOME 50 workarounds."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# GNOME 51 app divergences: Calculator and Text Editor

These are **not** among the twelve workarounds above. In the plain `gnomeos-51`
run ([gnome-51-audit.md](gnome-51-audit.md) §Run evidence), Calculator and Text Editor scenarios diverged. In the `dakota:testing`
v1 gate run (same section), both apps were absent and their scenarios skipped; that run
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
