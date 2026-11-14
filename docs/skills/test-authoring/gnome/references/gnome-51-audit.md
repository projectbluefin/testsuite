---
name: gnome-51-audit
description: "Audit of GNOME 50-specific workarounds against GNOME 51 — per-workaround verdict, the live gnomeos-51 run evidence, the targeted probes behind each verdict, and qecore on GNOME 51."
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

| #   | Workaround                                                                                   | Status (GNOME 51)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Where                                                                                                          |
| --- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 1   | Re-prepend `global.context.unsafe_mode = true` before every `Shell.Eval` (GNOME 50 reset it) | **OBSOLETE ON 51** — §Targeted probes (round 2): `global.context.unsafe_mode`, read by a raw `Shell.Eval` that does not re-enable it, stayed `true` after a 3 s idle, an overview open and close over D-Bus, a notification, a GNOME Text Editor window opening and closing, and both screen-lock paths with their unlocks, on `dakota:testing` and `utah:testing`. GNOME 50's reset did not happen. Keep the prepend while any tested image runs GNOME 50; it is harmless. Modal dialogs other than the lock screen were not exercised                                                                                                                                                                                                                                                                                                  | `tests/smoke/features/steps/steps.py`; documented in `SKILL.md` "Screen Lock/Unlock" / "Overview search entry" |
| 2   | Double-quoted `Shell.Eval` results `(true, '"true"')`                                        | **OBSOLETE ON 51 as a version quirk** — §Targeted probes (round 2): `Shell.Eval` returns the result JSON-encoded on both images: `true` → `(true, 'true')`, `'abc'` → `(true, '"abc"')`, objects and arrays as JSON, `undefined` → `''`. A quoted `'"true"'` only appears when the expression evaluates to the string `"true"`. Keep `_eval_bool`'s optional quotes for string results                                                                                                                                                                                                                                                                                                                                                                                                                                                   | `tests/smoke/features/steps/steps.py`                                                                          |
| 3   | Extension `state=6` via `Shell.Eval` → use `GetExtensionInfo` D-Bus                          | **OBSOLETE ON 51** — §Targeted probes (round 2): for the 12 extensions sampled on each image (all `ACTIVE`), `Main.extensionManager.lookup(uuid).state` via `Shell.Eval` returned `1`, matching `GetExtensionInfo` (`1`) and `gnome-extensions show` (`ACTIVE`); GNOME 50's constant `6` did not occur. Keep `GetExtensionInfo`: it is the public API and needs no unsafe mode                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Extension state via D-Bus"                                  |
| 4   | `filler`/`frame` toplevel-role fallback + require populated subtree                          | **OBSOLETE ON 51 for every app measured** — §Targeted probes (round 3): on both images the toplevel of Files (`org.gnome.Nautilus`, 172 descendants) and Settings (`gnome-control-center`, 150), and on utah Firefox (29 children), was a populated `frame`; no `filler` toplevel and no bare childless `filler` occurred. Calculator, Text Editor and Clocks ship on neither image, so were not measured. Keep `{frame, filler}` and the populated-subtree check while any tested image runs GNOME 50                                                                                                                                                                                                                                                                                                                                   | `tests/shared/gnome_shell_steps.py`; `SKILL.md` "Window-role checks must prove the subtree is populated"       |
| 5   | Nautilus sidebar role (`home_folder_is_in_the_sidebar`)                                      | **OBSOLETE ON 51** — §Targeted probes (round 3): replaying the step's own search, its only match on both images was a `list item` named `Open Personal Folder` in the unnamed sidebar `list`: the pre-GNOME 50 role. GNOME 50's `button` did not occur in the sidebar (the `Home` `button` is the path bar's). The `Personal Folder` name match is what finds it. Keep accepting `button` while any tested image runs GNOME 50                                                                                                                                                                                                                                                                                                                                                                                                           | `tests/smoke/features/steps/gnome_files_steps.py`                                                              |
| 6   | Nautilus AT-SPI app-name handling (`FILES_APP_NAMES`, `_nautilus_app`)                       | **STILL REQUIRED** — §Targeted probes (round 3): Files registers in AT-SPI as `org.gnome.Nautilus` on both images, not the pre-GNOME 50 `nautilus`, so a lookup by `nautilus` alone finds nothing                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | `tests/smoke/features/steps/gnome_files_steps.py`                                                              |
| 7   | Ptyxis window title (`user@host:~`)                                                          | **STILL REQUIRED on `utah:testing`; not testable on `dakota:testing`** — §Targeted probes (round 2): on utah (`/usr/bin/ptyxis`) a new window was titled `Terminal` (WM class `org.gnome.Ptyxis`) and its AT-SPI frame was named `Terminal`, so a check for a `Ptyxis` title would fail. `dakota:testing` ships no Ptyxis (its terminal is Ghostty), which is why smoke-a skipped the scenario                                                                                                                                                                                                                                                                                                                                                                                                                                           | `tests/smoke/features/steps/gnome_apps_steps.py:34-38`                                                         |
| 8   | ScreenSaver D-Bus `Lock` (not `screenShield.lock(true)`)                                     | **OBSOLETE ON 51** — §Targeted probes (round 2): `Main.screenShield.lock(true)` via `Shell.Eval` locked the session on both images (`org.gnome.ScreenSaver.GetActive` → `true`), and `SetActive false` unlocked it; `org.gnome.ScreenSaver.Lock` behaved the same. GNOME 50's "deprecated and fails" no longer holds. Keep the D-Bus `Lock`: it is the public API and needs no unsafe mode                                                                                                                                                                                                                                                                                                                                                                                                                                               | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Screen Lock/Unlock D-Bus calls"                             |
| 9   | `Main.overview.visible` reads `false` in QEMU; do not assert it                              | **OBSOLETE ON 51** — the targeted probe (§Targeted probes) read `Main.overview.visible` as `false`, `true`, `false` across an overview open and close in QEMU on GNOME Shell 51.1, matching `OverviewActive` each time, on `dakota:testing` and `utah:testing`. Keep checking `OverviewActive`: it needs no `Shell.Eval` or unsafe mode                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | `tests/smoke/features/steps/steps.py`; `SKILL.md` "Activities overview (GNOME 50 QEMU)"                        |
| 10  | Notification banner dismissal check                                                          | **BROKEN ON 51 — fixed** — §Targeted probes (round 3): the GNOME 50 check also required `Main.messageTray._bannerBin` hidden, which GNOME 51 never does, and treated any visible banner as ours, so it always fell through to a force-dismiss and a warning and could not fail. After `CloseNotification` this scenario's notification leaves the tray; the banner still on screen is an earlier one (other scenarios and retries send without closing) that Shell holds while the session is idle. Each sent notification now gets a unique title, and the step checks that this one is neither the visible banner nor in the tray: it passes on both images ([43556476178](https://github.com/projectbluefin/testsuite/actions/runs/43556476178), [43556485608](https://github.com/projectbluefin/testsuite/actions/runs/43556485608)) | `tests/smoke/features/steps/gnome_notifications_steps.py`                                                      |
| 11  | Panel buttons `showing=False` before overview toggle                                         | **OBSOLETE ON 51** — the first probe read the Activities toggle as `showing=True`; §Targeted probes (round 2) found the clock (a `menu` with no accessible name, holding the date and time label) and the `System` menu in the same top-bar panel, and both read `showing=True` before, during and after an overview toggle on both images. GNOME 50's "every panel button reports `showing=False`" holds for none of the three                                                                                                                                                                                                                                                                                                                                                                                                          | `tests/shared/gnome_shell_steps.py`                                                                            |
| 12  | keyring skip on GDM restart                                                                  | **WORKS ON 51** — §Targeted probes (round 2): with qecore's keyring setup skipped, every smoke-b scenario passed on both images. The login keyring is unusable without it: on dakota the `login` collection exists but is locked; on utah `gnome-keyring-daemon` runs with no `login` collection (default alias `/`); a `secret-tool store` blocked until a 15 s timeout on both. No smoke scenario stores a secret. Whether qecore's setup, which restarts GDM, would still break the run is not measured: it would restart the session under test                                                                                                                                                                                                                                                                                      | `tests/smoke/features/environment.py`                                                                          |

Every row now has a GNOME 51 verdict from a targeted probe (§Targeted probes,
rounds 1–3). Still required on 51: row 6, and row 7 where Ptyxis ships
(`utah:testing`). Row 10 was broken and is fixed. The rest are obsolete on 51
or, for row 12, work without the workaround; keep their GNOME 50 paths while
any tested image runs GNOME 50.

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

### Targeted probes (rows 9 and 11)

A temporary smoke scenario (commit `3325e9d7`, removed before merge) read
`OverviewActive`, `Main.overview.visible` and the AT-SPI `showing` state of the
panel's buttons with the overview closed, open and closed again, sleeping 1–1.5 s
after each change. Both runs are `manual.yml`, `smoke-a`, GNOME Shell 51.1:

| Image            | Run                                                                                 | `Main.overview.visible` (closed → open → closed) | Activities `showing` |
| ---------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------ | -------------------- |
| `dakota:testing` | [43503238954](https://github.com/projectbluefin/testsuite/actions/runs/43503238954) | `false` → `true` → `false`                       | `True` in all three  |
| `utah:testing`   | [43503253168](https://github.com/projectbluefin/testsuite/actions/runs/43503253168) | `false` → `true` → `false`                       | `True` in all three  |

`OverviewActive` matched `Main.overview.visible` at every read. The utah run
failed only at the SELinux denial gate (utah#1198), after the probe passed.

### Targeted probes (round 2)

A second temporary smoke scenario (commits `59159501` and `337a7bb4`, removed
before merge) recorded, without asserting, rows 1, 2, 3, 7, 8, 12 and the clock
and System toggles of row 11. It ran last in `smoke-b` so its screen-lock test
could not disturb other scenarios. All four runs are `manual.yml`, `smoke-b`,
GNOME Shell 51.1:

| Image            | Rows                            | Run                                                                                 |
| ---------------- | ------------------------------- | ----------------------------------------------------------------------------------- |
| `dakota:testing` | 1, 2, 7, 8, 11 (Activities), 12 | [43534607984](https://github.com/projectbluefin/testsuite/actions/runs/43534607984) |
| `utah:testing`   | 1, 2, 7, 8, 11 (Activities), 12 | [43534623481](https://github.com/projectbluefin/testsuite/actions/runs/43534623481) |
| `dakota:testing` | 3, 11 (clock, System)           | [43536818854](https://github.com/projectbluefin/testsuite/actions/runs/43536818854) |
| `utah:testing`   | 3, 11 (clock, System)           | [43536832734](https://github.com/projectbluefin/testsuite/actions/runs/43536832734) |

What each reading did:

- **Rows 1, 2:** raw `Shell.Eval` reads of `global.context.unsafe_mode` after
  each event, and of a boolean, string, number, `null`, object, array and
  `undefined`.
- **Row 3:** `gnome-extensions list --enabled`, then per extension
  `GetExtensionInfo`, `Shell.Eval` of `lookup(uuid).state` and `gnome-extensions show`.
- **Rows 7, 8:** launched `ptyxis --new-window` and read window titles and AT-SPI
  frames; locked through both paths and read `GetActive` after each step.
- **Row 11:** every AT-SPI `panel` node; the top bar is the one holding
  `Activities`, the unnamed clock `menu` and the `System` `menu`.
- **Row 12:** the keyring daemon, `login` collection and default alias, then a
  `secret-tool store` with a 15 s timeout.

Every probe scenario passed. Both utah runs failed only at the SELinux denial
gate, on utah#1198's `chcon` `mac_admin` denials.

### Targeted probes (round 3)

A third temporary smoke scenario (commits `ea968538` to `e4aa74e5`, removed
before merge) read, in `smoke-b` on GNOME Shell 51.1 with qecore 4.19.3: each
app's AT-SPI toplevels (row 4), the sidebar matches of the step's own search
(row 5), the application names (row 6), and for row 10 the message tray, the
visible banner's notification and the session idle time around
`CloseNotification`, before and after one uinput keypress.

| Image            | Run                                                                                 |
| ---------------- | ----------------------------------------------------------------------------------- |
| `dakota:testing` | [43549588532](https://github.com/projectbluefin/testsuite/actions/runs/43549588532) |
| `utah:testing`   | [43549598764](https://github.com/projectbluefin/testsuite/actions/runs/43549598764) |

Row 10 in numbers: the visible banner was never this scenario's notification
but an earlier one (`Settings`, or another test notification left open); this
scenario's notification left the tray within 1 s of `CloseNotification`; the
session had been idle 34–282 s; one `<Shift>` reset the idle time and the held
banner cleared within 2.3 s. The same hold showed with the close sent at once or
after 1 s (runs 43540402711, 43544509681, 43546740107, 43554149449,
43554157456). The fixed step passed in smoke-a on both images (runs above).

### qecore on GNOME 51

Every GNOME 51 run above used qecore 4.19.3 (the pin in
`container/Containerfile.runner`, `container/Containerfile.gnomeos-harness`
and the gnome-e2e action), with dogtail 2.0.3 and behave 1.3.3, read from the
test process on both images. qecore-headless and its common steps work there:
smoke-a, smoke-b and the GNOME OS canary pass. qecore's releases since (4.20 to
4.22.1) name no GNOME 51 change; 4.22 adds handling for a missing keyring,
which matches row 12 on utah.

## Run findings — Calculator and Text Editor divergences

These are not among the twelve workarounds. The plain `gnomeos-51` run's
Calculator display lookup and Text Editor `Ctrl+N`/`Ctrl+Q` failures are in
[gnome-51-app-divergences.md](gnome-51-app-divergences.md) (documented, not fixed).

## Bluefin-only failures (expected on gnomeos-51 — not divergences)

The 11 failures in smoke-a and smoke-b are Bluefin's bundled extensions,
power-status, tailscale, fastfetch, and failed-units. These are **not** part of
this audit — plain gnomeos-51 has none of Bluefin's extensions and a different
power-management layout. Do not open GNOME 51 workarounds for them.

## Moving a LIKELY-KEEP row to confirmed

Run the targeted scenarios on gnomeos-51 via the run target above and record the
result here with the run URL. Until then, keep the GNOME 50 workaround.
