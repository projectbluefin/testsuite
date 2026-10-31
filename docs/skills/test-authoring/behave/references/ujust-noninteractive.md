---
name: ujust-noninteractive
description: "Which ujust recipes can be driven non-interactively, and why the rest stay @pending."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Ujust Noninteractive

## `toggle-updates` — non-interactive via `ACTION` (verified 2026-08)

`system_files/shared/usr/share/ublue-os/just/update.just` in
`projectbluefin/common` declares the recipe as `toggle-updates ACTION="prompt":`
and now reads the parameter through just's `{{ ACTION }}` interpolation (shebang
recipe bodies receive parameters only via interpolation, never as positional
arguments):

- `ujust toggle-updates enable` / `disable` / `cancel` (case-insensitive)
  select the action directly and skip the `gum choose` prompt. This is the
  non-interactive entry point tracked in `projectbluefin/testsuite#499`.
- Any other value — including the default `ACTION="prompt"` — keeps the
  interactive behavior and blocks on `gum choose`.

Shipping common (`e33665e2`) toggles **two** timers when `uupd.timer` exists:
`enable` runs `systemctl enable uupd.timer uupd-resume.timer` and starts
`uupd.timer`; `disable` runs `systemctl disable --now` on both.

Coverage lives in `tests/common/features/common_ujust.feature` (active, no
probe gate). The scenario snapshots `is-enabled`/`is-active` for both timers,
runs `cancel` (state must not change), `DISABLE`, then `enable` through the
recipe, asserts the confirmation line plus both timers' state after each
step, and restores the snapshot explicitly (with an `EXIT` trap as backstop),
then asserts the restore. Images built on a common layer older than the
`uupd-resume.timer` change fail this scenario by design.

Other safe non-interactive paths covered there: `ujust --summary` strict
parse plus the shared recipe inventory, `NO_COLOR=1 check-local-overrides`
emitting no ESC bytes (a planted `/etc` probe file guarantees a line to
colour), `bios-info` values (not labels), `toggle-testing` refusing an unknown
channel via a temp `IMAGE_INFO_FILE`, and `report --confirm abc` printing usage
(never pass a numeric issue without a TTY: that path posts).

## `toggle-devmode` has no non-interactive entry point (verified 2026-09)

`ujust toggle-devmode`
(`system_files/bluefin/usr/share/ublue-os/just/system.just` in
`projectbluefin/common`) is a `gum`-only interactive recipe: it renders a
`gum style` banner, then drives `gum confirm` / `gum choose` for the stack
picker. There is no argument or flag that selects an action headlessly.

It previously delegated to a Homebrew-installed helper CLI when that binary
was present, and testsuite covered the delegation in
`tests/common/features/common_devmode.feature`. That helper has been
deprecated and removed from every shipped image, so the delegation branch —
and the coverage that exercised it — no longer exist. The feature file, its
presence-probe skip tag in `tests/common/features/environment.py`, and the
`@devmode_cleanup` teardown hook were deleted with it.

`toggle-devmode` therefore sits in the same bucket as any other gum-gated
recipe: do not land a scenario for it until the recipe itself grows a
non-interactive argument, the way `toggle-updates` did above. Re-opening
`projectbluefin/testsuite#500` against `projectbluefin/common` is the correct
next step — the gap is a recipe interface gap, not a CI harness gap.
