---
name: suite-map
version: "1.0"
last_updated: "2026-07-29"
id: suite-map
one_line_purpose: Read the authoritative coverage matrix and @future gap list.
entry_point: docs/skills/test-authoring/suite-map/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [coverage, suites, matrix]
description: "Authoritative coverage matrix and @future gap list. Load during planning, coverage reviews, or when adding a new suite."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Suite Map and Coverage

Load when: deciding which suite to add a test to, checking existing coverage, or reviewing @future gaps.

## When to Use

- Choosing the correct suite for new coverage
- Determining which image variants run a suite
- Updating scenario counts after feature-file changes
- Verifying variant-specific tag semantics such as `@bluefin` and `@dakota_only`

## When NOT to Use

- GNOME AT-SPI implementation details → use `gnome.md`
- Behave step-authoring patterns or collision avoidance → use `behave.md`
- CI workflow internals or reusable action behavior → use `e2e-workflow.md`

## Core Process

1. Identify the suite affected by the change.
2. Confirm the suite/image matrix before adding variant-specific coverage.
3. Verify the correct scenario tags for that image family.
4. Update the coverage snapshot and per-suite counts when scenario totals change.
5. Cross-check the same totals in `docs/qa-review.md` before opening the PR.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It is only one scenario, the counts can wait." | Coverage drift compounds quickly; `suite-map.md` and `docs/qa-review.md` are co-authoritative. |
| "The tag name is obvious." | Variant gating is implemented in suite hooks; confirm the actual tag semantics before writing image-specific scenarios. |
| "Another skill file already mentions this suite." | This file is the source for suite-to-image mapping and coverage totals. |

## Red Flags

- Scenario totals changed but `suite-map.md` was not updated
- A variant-specific scenario was added without checking whether the image actually runs that suite
- A new tag was used without documenting its meaning here
- `suite-map.md` and `docs/qa-review.md` disagree on counts

## Verification

- [ ] Suite/image matrix still matches the intended coverage
- [ ] Variant tag semantics match the actual suite hook behavior
- [ ] Scenario totals here match `docs/qa-review.md`
- [ ] Notes describe timeless operating rules, not session history

> Coverage snapshot here and in `docs/qa-review.md` are co-authoritative — update both when scenario counts or gap status change.

## Variant matrix

Which suites run on which image. Any bootc/ostree GNOME image can run via the GitHub Action.

| Suite | `bluefin` | `bluefin-gdx` | `bluefin-nvidia-open` | `dakota` | `bazzite` | `gnomeos` | `flatcar` | Notes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| `smoke` | ✅ | ✅ | ✅ | ✅ | — | — | — | Core GNOME smoke; automatically sharded into `smoke-a` + `smoke-b` parallel jobs |
| `vanilla-gnome` | — | — | — | — | — | ✅ | — | Upstream GNOME baseline; `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-latest` |
| `bazzite` | — | — | — | — | ✅ | — | — | Bazzite extensions + shell behaviour |
| `developer` | ✅ | ✅ | — | — | — | — | — | Homebrew/Ptyxis |
| `software` | — | — | — | — | — | ✅ | — | Bazaar launch, search, config YAML validation, Flathub remote, permissions DB, Bazaar CLI presence/info/remote, and Flatpak per-app permission management active; upstream GNOME Software navigation scenarios are `@future` (#176) |
| `common` | ✅ | ✅ | ✅ | ✅ | — | — | — | Flatpak model/state, XDG portals, container runtime, polkit, shell env/sourcing, system scripts, ujust recipes, GSettings/dconf, immutable OS integrity |
| `lifecycle` | ✅ | — | ✅ | ✅ `@homed_migration` | — | — | — | bootc upgrade/rollback; SSH-mode; dakota: homed migration only |
| `security` | ✅ | — | ✅ | — | — | — | — | cosign + SELinux; SSH-mode |
| `hardware` | ✅ | — | — | — | — | — | — | udev rules syntax validation + emulated peripherals; SSH-mode |
| `dx` | — | ✅ | — | — | — | — | — | DX-only tools (VS Code, distrobox, Jupyter) |
| `nvidia` | — | — | ✅ | — | — | — | — | GPU driver validation; NVIDIA variant only |
| `flatcar` | — | — | — | — | — | — | ✅ | Flatcar OS boot and lifecycle |
| `kde-smoke` | — | — | — | — | — | — | — | KDE Plasma harness proof-of-concept; Aurora-only, all scenarios `@informational` |

**GitHub Action consumers**:
```yaml
uses: projectbluefin/testsuite/.github/workflows/e2e.yml@v1
with:
  image: <your-bootc-image>
  suites: smoke,common   # smoke and common each auto-shard into two parallel jobs
```
Passing `suites: smoke` expands to `smoke-a` + `smoke-b`, and `suites: common` expands to `common-a` + `common-b`. Both cut wall time by ~50%. New `.feature` files in these suites are picked up automatically.

GitHub Action suites (`smoke`, `vanilla-gnome`, `bazzite`, `developer`, `dx`, `software`, `common`, `lifecycle`) run on `ubuntu-latest`.
`security` and `hardware` (SSH-mode) are not yet in the GHA action. The original migration epics (#43, #44) are closed; the remaining gap is untracked — file a fresh issue before claiming this work.

Any bootc/ostree GNOME image can plug in `smoke` and `common` as a portable health gate — no Bluefin-specific knowledge required. See `README.md` → "For other bootc image maintainers" for minimum image requirements.

## PR gate model

- All consumer repos should gate on the `smoke` suite only.
- Nightly CI is gone; PR gates are now the only CI signal for promotion decisions.
- `e2e.yml` now caches OCI layers by image digest to speed repeated runs.
- For workflow internals, cache behavior, and troubleshooting, see [`docs/skills/ci-ops/e2e-workflow/SKILL.md`](../../ci-ops/e2e-workflow/SKILL.md).


**Trigger a lifecycle run manually**:
Go to **[projectbluefin/actions → Actions → bootc Upgrade and Rollback Test → Run workflow](https://github.com/projectbluefin/actions/actions/workflows/upgrade-test.yml)**.
Set `image` (e.g. `ghcr.io/ublue-os/bluefin:latest`), `suites: lifecycle`, `chunked_enabled: false`.
Set `chunked_enabled: true` once `ghcr.io/projectbluefin/bluefin:latest` ships zstd:chunked layers.

> **For lifecycle runs, use `upgrade-test.yml` in `projectbluefin/actions`** — it
> calls `e2e.yml` cross-repo and exposes the lifecycle-specific inputs (`chunked_enabled`,
> `test_ref`). `manual.yml` in this repo works for non-lifecycle suites (startup_failure
> was fixed in PR #245 by removing the `@main` ref suffix from the `uses:` line — the
> bare local path `uses: ./.github/workflows/e2e.yml` is fine). For lifecycle, prefer
> `upgrade-test.yml` because it has the richer input set lifecycle needs.

**Registry split:** `bluefin`, `bluefin-nvidia-open`, `dakota` → `ghcr.io/projectbluefin`. `bluefin-gdx`, `bazzite-gnome` → `ghcr.io/ublue-os`.

**Tag notes:**
- `bluefin`: `testing` (pre-release) + `stable` + `lts-testing` + `lts`
- `bluefin-gdx`: `stream10` = lts equivalent; `stream10-testing` = pre-release
- `bluefin-nvidia-open` / `bazzite-gnome`: `testing` + `stable`
- `dakota`: `testing` + `latest`

**Why these assignments:**
- `bluefin` does not ship GNOME Software (it ships Bazaar — `io.github.kolunmi.Bazaar`, a Flatpak software center) → the GNOME Software navigation scenarios are tagged `@future` (#176); Bazaar CLI presence/info/remote coverage is active in `bazaar.feature` and Bazaar config integrity coverage is active in `bazaar_config.feature`
- `bazzite` is not vanilla GNOME → only the bazzite suite runs against it (no vanilla-gnome)
- `bluefin-nvidia-open` is used because nvidia-open is built daily; nvidia services (`nvidia-persistenced`, `ublue-nvctk-cdi`) are in `IGNORED_FAILED_UNITS_IN_VM` — they always fail in QEMU without a physical GPU

## Scenario tags

| Tag | Meaning |
|---|---|
| `@smoke_suite` | Runs as part of the standard smoke suite |
| `@bluefin` | Smoke scenario runs only when the image name contains `bluefin`; smoke `environment.py` skips it elsewhere |
| `@dakota_only` | Scenario runs only when the image name contains `dakota`; the `smoke` and `common` `environment.py` files skip it elsewhere. Only the image **name** is matched, so the `projectbluefin` org name cannot false-positive |
| `@dx_only` / `@developer_suite` | DX variant only |
| `@nvidia_only` | NVIDIA variant only |
| `@flatcar_suite` | Flatcar OS only |
| `@hardware_emulation` | Requires full-hw VM spec (TPM, audio, watchdog) |
| `@pending` | Placeholder coverage gap; intentionally skipped until a valid harness exists |
| `@future` | Not yet implemented or blocked on infra |
| `@homed_migration` | systemd-homed migration scenarios; dakota lifecycle; SSH-mode; skip-safe when homed absent |
| `@regression` | Anchors a known incident regression guard; must remain active indefinitely |
| `@kde_smoke` | KDE Plasma smoke-suite identifier; used by `e2e.yml` suite registration (#645) |
| `@informational` | Bake-period tier; scenario runs and reports results but does not gate promotion until promoted to `@critical` |
| `@requires_cached_image` | Scenario needs the OCI image named in its own steps to be pre-pulled on the DUT; `tests/shared/image_cache.py` probes `podman image exists` from `before_scenario` and skips while it is absent. A **runtime capability gate** like `@requires_bctl`, not a non-runnable tag — never pair it with `@pending`/`@future`, which mask it (#501) |

## Coverage snapshot

> The numbers in this block are **generated** by `scripts/update_coverage_snapshot.py`
> from the `.feature` files. **Do not hand-edit the counts** — run the script.
> Only the per-suite Notes prose is hand-maintained (in the script's `SUITE_NOTES`).
> CI (`Coverage snapshot fresh` check) fails if this block is stale.

<!-- coverage-snapshot:start -->

526 scenarios across 72 feature files: 415 active, 0 quarantined, 111 `@future`/`@pending`/`@hardware_blocked`

| Suite | Scenarios | Active | Quarantined | Pending/Future | Notes |
|---|---|---|---|---|---|
| bazzite | 20 | 20 | 0 | 0 | Extension presence + shell behaviour |
| common | 121 | 101 | 0 | 20 | Signing assertions `@future` pending the ublue-os→projectbluefin policy migration; flatpak model/state, dconf defaults, immutability and portal socket checks `@pending` on CI infra; Flatpak model + state; XDG portal health + integration; container runtime (podman); polkit rules; shell env + sourcing; system scripts; ujust recipes; devmode via bctl (non-interactive contract + idempotent state-check gated `@requires_bctl`, group mutation `@pending` on CI polkit); GSettings/dconf defaults; immutable OS integrity; desktop entries; signing assertions; Dakota `ujust --choose` regression guard active (`@dakota_only`); `ujust report` is `@pending` on #706 until a Dakota lab run validates the mocked submit flow |
| developer | 23 | 7 | 0 | 16 | 6 brew + 6 ptyxis + 4 bctl now `@pending`: `brew-setup.service` masked in CI (#487) and the ptyxis AT-SPI restart issue (#368) |
| dx | 18 | 13 | 0 | 5 | distrobox create/install/export are active behind the `@requires_cached_image` runtime gate — they skip until `fedora-toolbox:latest` is pre-pulled on the VM (#501 / projectbluefin/lab#621) and activate without a feature-file edit; distrobox enter, JupyterLab, brew, mise remain `@pending` on infra gaps |
| flatcar | 13 | 12 | 0 | 1 | boot (7 active) + lifecycle (5 active); 1 `@future` (boot from installed target disk — needs KubeVirt boot-order support in `projectbluefin/lab`) |
| hardware | 13 | 13 | 0 | 0 | udev rules syntax validation (ZSA, Apple SuperDrive, Framework 16, AMD s2idle, Wooting, VIIA); emulated peripherals driven by shared SSH steps |
| installer | 3 | 3 | 0 | 0 | post-boot assertions for installer-driven installs (UEFI, Flatpak exclusion, LUKS cmdline) |
| kde-smoke | 13 | 13 | 0 | 0 | Plasma session, D-Bus services, AT-SPI tree, KWin output, one KCM, Dolphin, Konsole, Kickoff; all `@informational` |
| lifecycle | 33 | 29 | 0 | 4 | bootc upgrade / rollback / migration; pin + switch are `@future` (pin races the staged-deployment writer; switch needs a valid alternate image ref) |
| nvidia | 12 | 0 | 0 | 12 | `@future` / `@hardware_blocked` until GPU passthrough exists in the lab |
| security | 15 | 15 | 0 | 0 | cosign verify: projectbluefin (bluefin, lts, dakota) + ublue-os (latest, LTS, DX, nvidia, GTS, DX-nvidia, negative) |
| smoke | 196 | 151 | 0 | 45 | 39 `@pending` flatpak-permission audits blocked on CI never seeding system Flatpaks; MIME handler coverage (Firefox/Papers/Loupe/Text Editor/video); GNOME accessibility (AT-SPI daemon, high-contrast toggle, a11y panel); display fractional/integer scaling via Mutter DisplayConfig; Bluefin desktop identity (Wayland, hardware accel, Dash to Dock); GNOME regression guards in gnome_regression.feature; Dakota sudo-rs privilege and PAM checks |
| software | 33 | 25 | 0 | 8 | Bazaar launch + search + CLI presence/info/remote + config YAML validation active on bluefin; Bazaar UI tests rewritten for actual Bazaar layout; CLI (Flathub remote + permissions DB) active on all images; Flatpak per-app permission management active on all images; upstream GNOME Software scenarios are `@future` (#176) |
| vanilla-gnome | 13 | 13 | 0 | 0 | Baseline GNOME Shell parity check; runs on any GNOME image |

<!-- coverage-snapshot:end -->

### How the snapshot is derived

A mechanical recount of `tests/*/features/**/*.feature`. A scenario counts once, in
tag precedence order: `@quarantine` > `@hardware_blocked` > `@future` > `@pending` > active.

> **Quarantine backlog is now zero.** Every scenario that was quarantined for an
> infrastructure or unshipped-feature blocker was reclassified to `@pending`/`@future` with a
> named blocker, and the one regression guard whose upstream bug is fixed was re-activated.
> `@quarantine` is reserved for genuinely flaky regression coverage under active repair —
> if you reach for it, you are committing to fixing the scenario inside 30 days.


> **Non-runnable tags are enforced in two independent layers.** A tag is only truly
> non-runnable if BOTH are updated — miss one and the scenario still executes:
>
> | Layer | File | What it does |
> |---|---|---|
> | CI tag filter | `.github/workflows/e2e.yml` (`BEHAVE_TAG_ARGS`) and `NON_RUNNABLE_TAGS` in `tests/shared/behave_retry.py` | Never selects the scenario. Each tag needs its OWN `--tags ~@tag`; behave ANDs separate `--tags` flags but ORs comma-joined tags in one flag. |
> | Runtime skip | `_SKIP_TAGS` in `tests/shared/quarantine.py` | Skips it from `before_scenario`, and decides which reason is reported. Order here must match the precedence above. |
>
> `@future` and `@pending` are enforced **only** at the runtime layer; `@quarantine` and
> `@hardware_blocked` are enforced at both. When adding a new non-runnable tag, update
> `_SKIP_TAGS`, `_SKIP_REASONS`, `NON_RUNNABLE_TAGS`, `BEHAVE_TAG_ARGS`, and add a
> regression test to `tests/unit/test_quarantine.py` and
> `tests/unit/test_behave_retry_helpers.py`.
>
> A tag that is only ever applied alongside another non-runnable tag is **masked**: it looks
> enforced but is not. `@hardware_blocked` was masked by `@future` on
> `tests/nvidia/features/gpu.feature` and went unenforced. Assert each tag independently.

## Known coverage gaps

| Area | Priority | Notes |
|---|---|---|
| Bazaar / Flatpak management GUI | High | Bazaar CLI/config integrity coverage active; GUI navigation pending GNOME 50 AT-SPI re-validation |
| Flatpak permission management | Low | Flatseal / per-app permissions not exercised |
| OOBE / first-boot | Low | True GDM → GIS flow is not covered; qecore assumes autologin. The [design spike](../../../archive/spikes/oobe-first-boot.md) recommends a bounded mock-mode accessibility probe and defers a fresh-disk QEMU input lane pending maintainer approval. |
| `ujust toggle-updates` | Medium | Blocked upstream in `projectbluefin/common`. `update.just` declares `toggle-updates ACTION="prompt":` but never reads `ACTION`. On images with `bctl` the recipe `exec`s `bctl --screen updates`, a GUI panel; only without `bctl` does it fall back to a `gum choose` prompt, which blocks non-interactive runs. Neither branch offers a non-interactive entry point. Scenario stays `@pending @wip` in `common_ujust.feature`. Next step: `projectbluefin/common` must honour `ACTION`; tracked in `projectbluefin/testsuite#499`. |
| `ujust toggle-devmode` group mutation | Medium | Non-interactive contract now exists: `bctl devmode --enable/--disable` (bluefinctl), which `toggle-devmode` execs to when `bctl` is present. Presence + idempotent state-check are covered in `common_devmode.feature`, gated `@requires_bctl` because bluefinctl is a Homebrew preinstall and `brew-setup.service` is masked in QEMU CI (#487). The actual group-mutating branch calls `pkexec usermod`, which requires an authentication agent bound to a real login session — unavailable over plain SSH. Scenario stays `@pending @wip`. Next step: a CI/lab-side non-interactive polkit or session-agent contract for `pkexec`; tracked in `projectbluefin/testsuite#500`. |
| uupd conditional suppression | Medium | Battery and metered-network checks are not covered: uupd reads UPower and NetworkManager system-bus properties, while testsuite has no supported isolated state-injection contract. Do not use `/sys/class/power_supply` or GNOME proxy settings as substitutes. Next step: add a lab/image-owned simulation hook, then cover the upstream `/etc/uupd/config.json` contract. |

### Skipped-coverage breakdown

Why the `@pending`/`@future` scenarios above cannot run today.

| Scenario | Suite | Tag | Blocked by |
|---|---|---|---|
| MIME defaults PDF/PNG/video (×3) | smoke | `@pending` | Fedora system mimeapps.list sets Firefox as default; Flatpak apps don't override at system level (#529) |
| flatpak_permissions system-wide installs (×39) | smoke | `@pending` | `flatpak-preinstall.service` masked in `e2e.yml` and `/var/lib/flatpak` never seeded |
| common flatpak model/state (×4) | common | `@pending` | flatpak-preinstall.service masked in CI; /var not preserved from OCI build |
| common dconf (×4) | common | `@pending` | gsettings/dconf schema defaults; Ptyxis palette is user-session state |
| common immutable (×2) | common | `@pending` | rpm-ostree/bootc status failing in fresh QEMU bootc install |
| common portals podman.socket (×1) | common | `@pending` | user socket not active in non-interactive CI session |
| common ujust changelogs (×1) | common | `@pending` | glow not available (brew-setup.service masked in CI, #487) |
| common scripts ublue-update timer (×1) | common | `@pending` | ublue-update.timer not enabled in CI images |
| common services flatpak (×2) | common | `@pending` | flatpak-preinstall.service masked; /var/lib/flatpak not seeded |
| GNOME Online Accounts provider list (×1) | smoke | `@pending` | session auto-locks during the long smoke run; AT-SPI cannot see panel rows |
| Screenshot portal PNG (×1) | common | `@pending` | portal backend emits no usable Request::Response headlessly |

### Reclassified in #679 (formerly `@quarantine`)

Quarantine is for flaky regression coverage that will be repaired soon. All 90 quarantined
scenarios were blocked on infrastructure or unshipped features rather than flakiness, so 89
were converted to `@pending`/`@future` with a named blocker and 1 (the composefs capability
regression guard) was re-activated because its upstream bug — projectbluefin/dakota#841 — is
closed. The highest-signal conversions are listed below; the rest appear in the
skipped-coverage table above.

| Scenario | Suite | New tag | Blocked by |
|---|---|---|---|
| brew (×6) | developer | `@pending` | `brew-setup.service` masked in `e2e.yml` (#487) |
| bctl (×4) | developer | `@pending` | `brew-setup.service` masked in `e2e.yml`, so bctl (installed via Homebrew) is never provisioned in CI; dedicated CI job to unmask it is design-gated (#487) |
| ptyxis: `@brew` (×1) | developer | `@pending` | brew must be initialized first (#487) |
| ptyxis: `@input`, `@podman`, `@regression`, `@new_tab`, `@close` (×5) | developer | `@pending` | AT-SPI restart issue in CI (#368) — ptyxis reopens between scenarios but the new process isn't reliably accessible |
| distrobox enter (×1) | dx | `@pending` | pulls `fedora:latest`; no pre-pull in CI, times out |
| distrobox create/install/export (×3) | dx | `@requires_cached_image` | Active, gated at runtime, **not** `@pending`. `tests/shared/image_cache.py` probes `podman image exists` for the image each scenario names and skips while `fedora-toolbox:latest` is absent from the VM's podman store. Self-activating once the lab-side OCI image pre-pull lands (#501, tracked in projectbluefin/lab#621) — no feature-file edit needed |
| JupyterLab (×1) | dx | `@pending` | not preinstalled in DX image |
| brew + mise (×3) | dx | `@pending` | `brew-setup.service` masked (#487) — mise uses brew-installed shims |
| ujust report confirm validation (×1) | smoke | `@pending` | `just` template change not in the booted image; awaiting rebuild |
| GNOME Software navigation/regression/close (×6) | software | `@future` | Bluefin ships Bazaar, not GNOME Software (#176) |
| flatpak install/uninstall round-trip (×1) | software | `@future` | gnomeos/GNOME 50 startup path unverified (#176); also slow network I/O |
| common signing (×2) | common | `@future` | signing policy not yet enforced upstream; mid-migration ublue-os → projectbluefin |
| bootc pin (×1) | lifecycle | `@future` | `bootc pin` races the staged-deployment writer in a fresh QEMU install |
| bootc switch (×1) | lifecycle | `@future` | mutates VM image variant; needs cross-variant golden-disk testing |

## @future inventory

Find remaining stubs:
```bash
just list-stubs
# or
grep -r "@future" tests/*/features/*.feature
```

Activate a `@future` scenario when all three conditions are met:
1. VM spec supports the required hardware/feature
2. Step implementations are complete
3. Suite runs cleanly via the GHA action

When activating: remove `@future`, update this file's coverage snapshot, update `docs/qa-review.md`.

## smoke vs vanilla-gnome

`smoke=failed` + `vanilla-gnome=passed` → Bluefin regression.  
`smoke=failed` + `vanilla-gnome=failed` → upstream GNOME issue.  
`vanilla-gnome` runs exclusively against `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-latest` — the official upstream GNOME OS bootc image — so results are directly comparable to what GNOME ships.  
Comparison commands and manual inspection procedure → `docs/runbook.md`.
