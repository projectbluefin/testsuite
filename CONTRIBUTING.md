# Contributing to testsuite

This repo is the test framework and suite for GNOME- and KDE-based bootc images. GNOME coverage uses headless automation with behave + qecore + dogtail; KDE Plasma coverage uses behave + KDE's `selenium-webdriver-at-spi` bridge. Both are backed by SSH-based system health checks.

| Concern | Repo |
|---|---|
| Test content (features, steps, helpers) | `testsuite` (this repo) |
| Infrastructure (ArgoCD, KubeVirt, manifests) | [`projectbluefin/lab`](https://github.com/projectbluefin/lab) |

## Suites at a glance

| Suite | Mode | Purpose |
|---|---|---|
| `smoke` | GUI (qecore/dogtail) | Core GNOME, MIME handlers, accessibility |
| `common` | SSH | Portable system health: Flatpak, portals, polkit, shell |
| `vanilla-gnome` | GUI | Upstream GNOME OS baseline |
| `extensions` | Guest-local GUI/Shell probes | Four Hive extension lifecycle/behavior profiles; GNOME OS guest proven (#908), candidate staging pending (#909) |
| `developer` | GUI | Homebrew/Ptyxis on developer variant |
| `dx` | SSH+GUI | VS Code, distrobox, JupyterLab, mise |
| `software` | SSH+GUI | Bazaar app store and Flatpak CLI health |
| `lifecycle` | SSH | bootc upgrade/rollback/migration |
| `security` | SSH | cosign signature verification |
| `hardware` | SSH | udev rules, emulated peripherals |
| `bazzite` | GUI | Bazzite-specific extensions |
| `flatcar` | SSH | Flatcar OS boot and lifecycle |
| `kde-smoke` | GUI (WebDriver/AT-SPI) | KDE Plasma harness proof-of-concept; Aurora-only, `@informational` |

## Local setup

```bash
pip install behave qecore dogtail
```

> `qecore-headless` is the runner binary installed by `qecore` — do not install it separately.

For the `kde-smoke` suite, install `selenium` instead of `qecore`/`dogtail`; unit tests import
`tests/shared/kde_webdriver.py`, which requires it. The KDE bridge itself
(`selenium-webdriver-at-spi`) runs on the device under test, not locally — it is not packaged in
Fedora and is installed by `scripts/install-kde-webdriver.sh`.

Full GUI runs require a live Wayland + AT-SPI session. For most changes, use the GitHub Action workflow.

## Validation (run before every PR)

```bash
ruff check tests/ --select E,F,W --ignore E501   # lint
behave --dry-run tests/<suite>/features           # if you touched .feature files
python3 -m pytest tests/unit/ -q                  # unit tests
python3 scripts/validate_docs.py                  # markdown + skill front matter
python3 scripts/generate_skill_index.py --check   # skill catalog is in sync
just list-stubs                                   # unimplemented @future scenarios
```

## Agent rules and patterns

For the agent entry point, mandatory gates, and skill loading rules, see
[`AGENTS.md`](AGENTS.md) and the task router at [`docs/SKILL.md`](docs/SKILL.md).
Factory-wide policy (label workflow, governance, onboarding contract) is owned by
[`projectbluefin/common`](https://github.com/projectbluefin/common/blob/main/docs/skills/factory-onboarding.md)
and is linked, not copied, from this repo.

## PRs target `main`

Open a PR with a [Conventional Commits](https://www.conventionalcommits.org/) title. CI must be green before enqueueing.

There is no cap on how many PRs may be open at once, but **two open PRs must not
modify the same file**. Check for overlap before opening one:

```bash
gh pr list --repo projectbluefin/testsuite --state open --json number,files \
  --jq '.[] | {number, files: [.files[].path]}'
```

This repo uses a merge queue; enqueue with:

```bash
gh pr merge <NUMBER> --repo projectbluefin/testsuite --squash --auto
```
