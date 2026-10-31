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

Pin applicability is explicit, not probed. Utah `sha256:a0baa947` ships the
common-main recipe; Bluefin `sha256:460d3a74` consumes an older common layer
whose `toggle-updates` runs `systemctl enable|disable uupd.timer` only (no
`--now`, no `uupd-resume.timer`) and whose `check-local-overrides` still emits
the RESET escape under `NO_COLOR=1`. `tests/common/features/common_ujust.feature`
therefore carries two toggle scenarios:

- `@utah_only`: the common-main contract. Snapshots `is-enabled`/`is-active`
  for both timers, runs `cancel` (no change), `DISABLE`, `enable`, asserts the
  confirmation line plus both timers' enabled state and `uupd.timer` activity.
- `@skip_utah`: the Bluefin pin. Asserts `uupd.timer` enablement flips and
  `uupd-resume.timer` is untouched.

Both restore the snapshot explicitly (with an `EXIT` trap as backstop) and
assert the restore. The NO_COLOR ESC-byte check is `@utah_only` for the same
reason; every Bluefin-family image runs the colour-stripped
planted-`/etc`-file listing check. When Bluefin bumps its common pin past the
`uupd-resume.timer` and #1190 changes, drop the `@skip_utah` toggle scenario
and the `@utah_only` tags.

Other safe non-interactive paths covered there: `ujust --summary` strict
parse plus the shared recipe inventory, `NO_COLOR=1 check-local-overrides`
emitting no ESC bytes (a planted `/etc` probe file guarantees a line to
colour), `bios-info` values (not labels), `toggle-testing` refusing an unknown
channel via a temp `IMAGE_INFO_FILE`, and `report --confirm abc` printing usage
(never pass a numeric issue without a TTY: that path posts). The report check
is `@skip_utah`: Utah overrides `report` in `60-custom.just`, and its routing
defect is owned by `utah_os.feature`.

## `bazaar-preview` — safe refusal path (verified 2026-10)

`ujust bazaar-preview <path>` checks for `bazaar.yaml`, `curated.yaml`, and
`blocklist.yaml` under `<path>/system_files/bluefin/etc/bazaar` before `sudo`,
so a nonexistent path is non-mutating: it must print `Missing …` plus
`Usage: ujust bazaar-preview /path/to/common` and exit 1. Never pass a real
checkout; that path writes `/etc/bazaar` and launches Bazaar.

At common `e33665e2` the recipe body reads shell `${source}` instead of the
just parameter `{{ source }}`, so `set -u` aborts with `source: unbound
variable` on Bluefin and Utah. `common_ujust.feature` keeps that scenario
failing until the recipe is fixed. Dakota does not ship the recipe.

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
