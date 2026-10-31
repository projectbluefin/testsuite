---
name: flatpak-permissions
description: "Flatpak per-app permission coverage via the CLI."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Flatpak Permissions

Lessons from #710. Read alongside the Flatpak section of the behave SKILL.

## `flatpak permissions <table>` succeeds for tables that do not exist

`flatpak permissions no-such-table` exits 0 and prints nothing, so a return-code-only
assertion never proves the table exists. The same is true over D-Bus:
`org.freedesktop.impl.portal.PermissionStore.List` and `.Lookup` do not distinguish a
missing table either. Assert on output content — rows are tab separated with the table
name in column 0, and an existing-but-empty table prints the `No permissions` sentinel.

To prove the documents backend is actually present, call
`org.freedesktop.portal.Documents.GetMountPoint`; it is the only call that fails when
the portal is absent (it returns `(b'/run/user/<uid>/doc',)` when present). The step
`Flatpak documents portal reports a mount point` wraps it.

## "No overrides exist" must cover `[Environment]`, not just `[Context]`

`flatpak override --user --show` keyfiles have both a `[Context]` and an
`[Environment]` section. A check that only walks `[Context]` keys reports "no
overrides" while `BLUEFIN_TESTSUITE=1` is still injected into the sandbox. Parse
section headers and treat any entry in either section as an override.

## Cleanup belongs in `after_scenario`, not in trailing steps

A `Then Reset flatpak user overrides for ...` step only runs when every preceding step
passed. One failure leaves the synthetic override installed and contaminates the next
scenario and every rerun. Put the reset in `after_scenario` in
`tests/software/features/environment.py` (`_reset_flatpak_permission_probe`) so it runs
unconditionally; the trailing step may stay as an in-scenario assertion.

## A sweep that passes on an empty install set is not coverage

`Every installed flatpak app exposes a parsable permission set` iterates `flatpak list`,
and CI — where `flatpak-preinstall.service` is masked and `/var/lib/flatpak` is not
seeded — is exactly the empty-set case, so the scenario was always green while
asserting nothing. It is `@pending` on #706 until the lab seeds a guaranteed-present
Flatpak. Never ship a scenario whose only CI behaviour is a vacuous pass; tag it with a
named blocker instead.

## `_flatpak` takes `context` first

`tests/software/features/steps/steps.py` defines `_flatpak(context, args, timeout=10)`.
Calling `_flatpak([...])` raises `TypeError` at runtime, and unit mocks that accept
`*args` hide it. Unit-test the call signature (`inspect.signature`) or assert the mock
was called with `context` as the first positional argument.

## Smoke audits pin exact filesystem grants (#1073)

`tests/smoke/features/flatpak_permissions.feature` compares the full effective
`[Context] filesystems` set (`_flatpak_filesystems` keyfile-parses
`flatpak info --system --show-permissions`, which merges image overrides) against
an exact list, so both widening and narrowing fail with the diff. Only apps in
`flatpak-app-list.txt` are active, tagged `@ci_seeded_flatpak`; the rest stay
`@pending`. `@bluefin` alone is too broad: it also matches bazzite and common
refs, which `e2e.yml` never preloads (its condition is `contains(inputs.image,
'/bluefin') || contains(inputs.image, '/utah')`), so the tag gate in the smoke
`environment.py` mirrors that condition and a missing app still fails on Bluefin
and Utah. Take expectations from the installed Flathub build plus any
`/usr/share/ublue-os/flatpak-overrides/<id>` the image links in via tmpfiles
(Bazaar adds `host-etc`). Upstream grants that look broad (Loupe `host`, Papers
`home:ro`) are pinned, not asserted away — the audit is drift detection.

## Installing a real Flatpak over SSH (FlatPark Compass, #1073)

`compass_flatpark.feature` is the CLI install/uninstall round-trip
(`bazaar_transaction.feature` drives one through Bazaar's UI). What it needed:

- **Not `_flatpak`.** Its 10 s timeout cannot cover an extra-data install (Compass
  downloads a ~71 MB AppImage from github.com at install time). Use `Run long SSH
  command` (900 s).
- **`sudo -n` for `--system`.** The SSH session has no polkit agent; `sudo -n` fails
  fast instead of hanging on a prompt. Keep the flatpak argv identical to the product's
  (`flatpak install -y --system flatpark org.tunaos.compass`).
- **Arch gate as a step.** FlatPark builds Compass `only-arches: x86_64`; a
  `uname -m` step calls `context.scenario.skip(...)` on anything else, so aarch64
  reports a skip, not a failure.
- **Cleanup via `context.add_cleanup` from a step.** The same step first removes any
  leftover install, then registers the removal, so it runs even when a later step
  fails, without touching `environment.py`.
- **Parse the grant list, never regex it.** Parse `flatpak info --system
  --show-permissions` with `context_values` and compare the grant name before `:`
  (`home`, `~`, `host`); a `filesystems=(host|home)` regex only sees the first
  value and also matches `host-os:ro`, a legitimate read-only grant.
- **Data survives uninstall.** Write a marker under `~/.var/app/<id>/` before
  `flatpak uninstall` without `--delete-data`, then read it back.
- **Run the app across `flatpak run` instances.** Only `$XDG_RUNTIME_DIR/app/<id>`
  is shared between instances on every Flatpak version. Flatpak 1.18 also shares a
  per-app `xdg-run` tmpfs, but older hosts may not. Point Compass's `COMPASS_SOCKET`
  at `app/<id>`, then start `serve --no-hotkey` in the GNOME session
  (`. /tmp/session.env`). Drive `ping`, `query`, `deeplink` and `shutdown` from
  second `flatpak run` instances. `flatpak ps` proves the instance exists and exits.
- **Compass behaviour, not just packaging.** `query --json --provider applications
  <Name>` must return `applications:<desktop id>`, as upstream's VM gate asserts
  (`checks.sh flatpak-apps`). Take `<Name>` from the host's desktop entry, which
  the sandbox reads through `host-os:ro`. For deeplinks, run `gio open
  compass://launch/applications/<id>` with `COMPASS_SOCKET` exported: GIO runs the
  exported `UrlHandler.desktop`, and flatpak passes the variable into the sandbox.
  `gio` exits 0 even when the handler fails, so the proof is a probe entry in
  `~/.local/share/applications` whose `Exec` touches a host file through
  `flatpak-spawn --host`. Create that entry before `flatpak run`, because
  `xdg-data/applications` is bound only if the directory exists. Poll for the
  file inside the same SSH command so that Dakota's `KillUserProcesses` does not
  kill gio's child.
- **Start long-lived processes as a user unit:** `systemd-run --user --collect
  --expand-environment=no --unit=<name> -p StandardOutput=truncate:<log>
  -p StandardError=inherit sh -c '…'`. Dakota's logind keeps the built-in
  `KillUserProcesses=yes` (Utah sets `no`), so anything left running by an SSH
  command, even under `setsid`, dies when that SSH session closes. A plain
  `cmd >log 2>&1 &` is worse: the backgrounded list holds `run_ssh`'s pipes until
  its 60 s timeout. Stop the unit in cleanup.
- **URL handlers: `gio mime`, not `xdg-mime`.** Dakota ships no `xdg-utils`. Take
  `XDG_DATA_DIRS` from `/usr/lib/systemd/user-environment-generators/60-flatpak` (what
  the session gets) so the Flatpak exports are searched. GIO hides desktop files
  whose `Exec` binary is missing, so only real exports resolve.
- **Image defaults differ.** common main enables `compass@tunaos.org` in its Bluefin
  schema override, but Dakota's common pin and Bluefin's extension set may not ship
  it. Read the compiled default with
  `GSETTINGS_BACKEND=memory gsettings get org.gnome.shell enabled-extensions` (ignores
  user dconf) and skip when the image does not enable it.
