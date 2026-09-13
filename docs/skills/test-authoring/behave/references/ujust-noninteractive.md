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

Asserting the timer state directly (`systemctl enable/disable uupd.timer`)
would test systemd, not the recipe, so it does not close the coverage gap.

Coverage lives in `tests/common/features/common_ujust.feature` behind a
`@requires_toggle_action` tag: the environment probes the recipe definition
with `ujust --show toggle-updates 2>/dev/null | grep -q 'ACTION_VALUE'`
rather than running `ujust toggle-updates cancel`. Running without a TTY
caused older unpatched recipes to fail in `gum choose` and set `SELECTED_OPTION=""`,
which hit `[[ "${SELECTED_OPTION}" == "Cancel" || "${SELECTED_OPTION}" == "" ]] && exit 0`,
falsely passing on unpatched images. Probing the recipe body for `ACTION_VALUE`
reliably skips the scenario on images that have not shipped the contract yet.
The scenario flips the update timer through the recipe itself (detecting
`uupd.timer`, falling back to `rpm-ostreed-automatic.timer`, matching the
recipe's own logic), asserts the state changed and the recipe's confirmation
output, then restores the original state so the scenario is repeatable.

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
