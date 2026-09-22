# testsuite

[![Live Dashboard](https://img.shields.io/badge/Live--Dashboard-Active-brightgreen?style=flat-square)](https://projectbluefin.github.io/testsuite/)

Automated behave-driven end-to-end testing for GNOME- and KDE-based bootc images. GNOME suites run headless Wayland sessions via qecore-headless + dogtail; the KDE suite drives Plasma through KDE's `selenium-webdriver-at-spi` bridge. Runs in QEMU on standard GitHub Actions runners — no self-hosted hardware required.

## Live Desktop Test Coverage

Coverage metrics and screenshots are published to the [Live Build Health Dashboard](https://projectbluefin.github.io/testsuite/). Per-suite counts are computed from the `.feature` files in this repo and served as shields.io endpoint badges from the `gh-pages` branch.

## Where this repo fits

```
projectbluefin/bluefin      ──┐
projectbluefin/bluefin-lts  ┼──▶ images ──▶ testsuite (e2e gate) ──▶ promotion
projectbluefin/dakota       ──┘

Any GNOME bootc image ──────────────────▶ testsuite (smoke + common)
```

For the canonical ownership boundary between this repo, [`projectbluefin/lab`](https://github.com/projectbluefin/lab), and downstream image repos, see [`docs/architecture.md`](docs/architecture.md).

## Test stack

| Layer | Tool | Purpose |
|---|---|---|
| BDD runner | behave | Gherkin scenarios and step binding |
| Session bridge | qecore-headless | Wayland/D-Bus session bootstrap |
| GUI automation | dogtail (AT-SPI) | Accessibility-tree interactions |
| Wayland bridge | gnome-ponytail-daemon | Coordinate injection support |
| Shell bridge | `org.gnome.Shell.Eval` | GNOME top-bar fallback |
| KDE GUI automation | `selenium-webdriver-at-spi` (W3C WebDriver) | Plasma AT-SPI interactions |
| KDE control plane | `org.kde.PlasmaShell` / KWin D-Bus | Diagnostics and session reset only — never the primary interaction path |
| SSH bridge | shared SSH steps | Out-of-VM system health assertions |

## What is tested

| Suite | Mode | Purpose |
|---|---|---|
| `smoke` | GUI (qecore) | Core GNOME, Settings, MIME handlers, accessibility, desktop identity |
| `common` | SSH | Portable health: Flatpak, portals, polkit, shell, immutability |
| `vanilla-gnome` | GUI | Upstream GNOME OS baseline |
| `developer` | GUI | Homebrew/Ptyxis on developer variant |
| `dx` | SSH+GUI | VS Code, distrobox, JupyterLab, mise |
| `software` | SSH+GUI | Bazaar app store, Flatpak CLI health |
| `lifecycle` | SSH | bootc upgrade / rollback / migration |
| `security` | SSH | cosign signature verification |
| `hardware` | SSH | udev rules, emulated peripherals |
| `bazzite` | GUI | Bazzite-specific extensions |
| `flatcar` | SSH | Flatcar OS boot and lifecycle |
| `kde-smoke` | GUI (WebDriver/AT-SPI) | KDE Plasma harness proof-of-concept; Aurora-only, all scenarios `@informational` |

`smoke` and `common` are designed to work against any GNOME bootc image. `kde-smoke` targets
KDE Plasma images and is not yet part of any promotion gate.

## Using as a GitHub Action

Add a reusable-workflow call to your bootc image repo:

```yaml
name: E2E Tests
on:
  pull_request:

jobs:
  test:
    uses: projectbluefin/testsuite/.github/workflows/e2e.yml@v1
    with:
      image: ghcr.io/<your-org>/<your-image>:latest
      suites: smoke,common
```

Pin to `@v1`; testsuite updates the `v1` tag automatically on each merge.

### Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `image` | string | — | OCI image to test |
| `suites` | string | `smoke` | Comma-separated suite names |
| `test_ref` | string | `main` | testsuite ref for test content |
| `skip_native_apps` | boolean | `false` | Skip `@native_app` scenarios |
| `screenshot_flatpaks` | string | `""` | Flatpak app IDs to screenshot |
| `chunked_enabled` | boolean | `false` | Enable `@zstd_chunked` scenarios |
| `memory` | string | `4096` | VM RAM in MB |
| `cpus` | string | `4` | VM CPU count |
| `free-disk-space` | boolean | `true` | Run disk cleanup before provisioning |

For full control, use the composite action at `projectbluefin/testsuite/.github/actions/gnome-e2e@v1`.

## Local development

- CI uses Python 3.14; match it locally.
- Install local Python pieces: `pip install behave qecore dogtail`.
- `gnome-ponytail-daemon` is baked into the image under test, not installed locally.
- Full GUI runs need a live Wayland + AT-SPI session; most contributors use the GitHub Action path.

## Agentic factory

This repo is agent-first: AI agents are primary maintainers of GNOME test coverage across both supported desktops (Bluefin and gnomeos). Agents file issues and submit PRs directly within the gates defined in `docs/skills/meta/human-gates/SKILL.md`. Every session produces two outputs: the work and a skill-doc update. See `AGENTS.md` for the agent entry point and `docs/SKILL.md` for the skill router.

## Further reading

- `AGENTS.md` — agent entry point and mandatory gates
- `CONTRIBUTING.md` — contributor setup and validation
- `docs/architecture.md` — canonical ownership boundary
- `docs/runbook.md` — operational commands
- `docs/qa-review.md` — release-trust review
- `docs/SKILL.md` — task → skill router and hard rules
- `docs/skills/index.json` — generated skill catalog (mirror: `docs/skills/index.md`)
- `docs/update-cadence-research.md` — design for testsuite-informed update cadence & promotion gating (issue #431)
