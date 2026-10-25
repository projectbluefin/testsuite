---
name: kde-suites
description: "KDE suite wiring in the reusable e2e.yml workflow."
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# KDE Suites in the Reusable E2E Workflow

This reference describes how `e2e.yml` supports KDE/Plasma test suites. It is the
workflow counterpart to the behave test content in `tests/kde-*`; changes to either
must stay in sync.


## Supported suites

| Suite | Sharded | Runner mode | DUT session |
|---|---|---|---|
| `kde-smoke` | `-a` / `-b` | Host-side KDE runner container | KDE Plasma (SDDM autologin) |
| `kde-apps` | no | Host-side KDE runner container | KDE Plasma (future) |
| `kde-settings` | no | Host-side KDE runner container | KDE Plasma (future) |
| `kde-session` | no | Host-side KDE runner container | KDE Plasma (future) |

`kde-smoke` is auto-sharded into `kde-smoke-a` and `kde-smoke-b` by the matrix
resolver, mirroring `smoke` and `common`.


## KDE setup is gated to KDE suites only

All KDE-specific workflow logic uses `startsWith(steps.shard.outputs.suite_dir, 'kde')`.
It must **not** fire for `smoke`, `common`, `developer`, `dx`, `software`,
`vanilla-gnome`, `bazzite`, or `lifecycle`.

Gated workflow behavior includes:

- Pulling the KDE runner image (`ghcr.io/projectbluefin/testsuite-kde-runner:kde-runner`) instead of the GNOME runner image.
  The `:kde-runner` tag is required — `build-kde-runner.yml` publishes only `:kde-runner` and `:kde-runner-<sha>`, never `:latest`.
- Loading the runner container on the GitHub Actions runner (host-side), not into the VM.
- Writing SDDM autologin and KDE determinism environment variables at disk-prep time.
- Skipping the GNOME-only `gnome-ponytail-daemon` install.
- Preparing a KDE/Plasma `/tmp/session.env` (`XDG_SESSION_DESKTOP=kde`, Qt a11y env).
- Installing `selenium-webdriver-at-spi` + `inputsynth` on the DUT.
- Running behave in the host-side KDE runner container.

GNOME suite behavior is unchanged.


## Runner-image split

| Image | Purpose | Ships `inputsynth`? | Ships `ssh`/`git`? |
|---|---|---|---|
| `ghcr.io/projectbluefin/testsuite:runner` | GNOME/qecore orchestration inside the VM | yes (built in) | n/a (in-VM) |
| `ghcr.io/projectbluefin/testsuite-kde-runner:kde-runner` | KDE/W3C WebDriver orchestration on the GHA runner | **no** | **yes** |

The KDE runner image is **host-side only**. It contains pinned `behave`, `selenium`,
`websocket-client`, `lxml`, and `PyYAML`, plus OS packages `openssh-clients` and
`git`. Tests drive the DUT over SSH (`tests/shared/ssh_steps.py` shells out to the
`ssh` binary) and CI needs `git` for checkout/version operations.

The image deliberately excludes `Appium-Python-Client`, `chromedriver`, and `odiff`
— see `docs/skills/test-authoring/kde/SKILL.md` §"Red Flags" and §"Verification"
for why each is wrong for this stack.

It does **not** contain `inputsynth`,
because `inputsynth` links `PlasmaWaylandProtocols`' `fake-input.xml` and the
Plasma/Qt/KWin ABI differs across Fedora, Ubuntu/Neon, and Arch/KDE Linux.

`inputsynth` and the matching `selenium-webdriver-at-spi` server are installed on
the device-under-test at test time by `scripts/install-kde-webdriver.sh`.

The `testsuite-kde-runner` image is built and published by
`.github/workflows/build-kde-runner.yml` (added in #640, merged).


## Per-DUT webdriver install

The script `scripts/install-kde-webdriver.sh` runs inside the VM and:

1. Detects the distro family from `/etc/os-release`.
2. Performs a version-skew check on the Plasma version and skips the suite with a
defined reason if the version is below the supported baseline (`5.27 LTS` / `6.x`).
3. Prefers distro packages (`dnf`, `apt`, `pacman`) when available.
4. Falls back to a pinned source build of
   `github.com/KDE/selenium-webdriver-at-spi` at commit
   `d45a21e8f1b3591dc921f0be85f1ecd834cbe413`. No floating refs or unpinned
   downloads are used.

If the install emits `KDE_WEBDRIVER_SKIP=<reason>`, the workflow writes a single
skipped scenario to `results/results.json` and exits cleanly instead of producing
phantom failures.


## Version skew / skip behavior

KDE suites must **skip** rather than fail when the DUT cannot be tested reliably.
Current skip conditions:

- Plasma version below `5.27` or `6.0`.
- Distro family not in the supported set (`fedora`, `debian`/`ubuntu`/`neon`,
  `arch`/`kde-linux`).

The skip is surfaced in the job log, the GitHub Step Summary, and the behave JSON
output.


## Supply-chain exception: per-DUT inputsynth

The repo rule is that no executable code is fetched at test time. `install-kde-webdriver.sh`
is a **documented exception**, because `inputsynth` is a Qt6 Wayland client linking
`PlasmaWaylandProtocols`' `fake-input` protocol and its ABI is tied to the DUT's
Plasma/Qt/KWin build. A centrally prebuilt binary is not portable across Fedora, Neon and
Arch-based KDE Linux — upstream KDE builds it inside the SUT for the same reason.

The exception is bounded by three requirements. Do not weaken any of them:

1. A distro package is always preferred; source build is a fallback only.
2. The source is pinned to an immutable commit SHA, never a branch or tag.
3. The checkout is verified against that SHA and the script fails loudly on mismatch.

## Shard resolution

`kde-smoke` auto-shards into `kde-smoke-a` / `kde-smoke-b`. Both the **expansion** set and
the **resolver** set must list `kde-smoke`. If only the expansion lists it, the shards resolve
to `tests/kde-smoke-a/features/`, a directory that does not exist, and every KDE job fails.
`tests/unit/test_e2e_suite_shards.py` runs both sets from `e2e.yml` and fails on any such
drift, for every suite.

## Container networking

The KDE runner is host-side and reaches the DUT over SSH at `127.0.0.1:2222`, the QEMU port
forward on the Actions runner. The WebDriver server is loopback-only in the guest and is
reached through the explicit host-loopback forward at `127.0.0.1:4723`. The container
therefore requires `--network=host`; in its own network namespace `127.0.0.1` is the
container, not the host. The workflow sets `KDE_WEBDRIVER_URL` to that endpoint and both
`NO_PROXY` and `no_proxy` for `127.0.0.1,localhost`, preventing inherited CI proxies from
intercepting Selenium traffic. It also needs `/tmp/vm_key` mounted read-only — setting
`SSH_KEY=/tmp/vm_key` without the mount leaves the key invisible inside the container.
