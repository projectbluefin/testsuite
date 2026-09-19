---
name: testsuite
version: "1.0"
last_updated: "2026-08-07"
id: testsuite
one_line_purpose: Route a testsuite task to the right skill and hard rules.
entry_point: docs/SKILL.md
category: meta
mcp_compliance_level: partial
status: active
dependencies: []
tags: [router, index, testsuite]
description: >-
  Task → skill router and hard-rule set for projectbluefin/testsuite. Load this
  first in every session, then load only the sub-skills your task needs.
metadata:
  type: manifest
  audience: agents
  maturity: stable
---

# testsuite skill router

This is the entry point required by the factory contract
([`projectbluefin/common` factory-onboarding](https://github.com/projectbluefin/common/blob/main/docs/skills/factory-onboarding.md)).
Read [`AGENTS.md`](../AGENTS.md) first for local authority (paths, ownership,
build commands, branch targets), then this file, then only the skills your task
needs. The generated catalog lives at [`skills/index.json`](skills/index.json)
with a human-readable mirror at [`skills/index.md`](skills/index.md).

## Hard rules

1. **Context7 before any library** — resolve qecore, dogtail, behave, gi.repository, AT-SPI docs via Context7; never guess API from training data.
2. **Shared SSH steps** — import from `tests/shared/ssh_steps.py`; never duplicate `_ssh()` in suite files.
3. **No ambiguous steps** — `grep -h "^@step" tests/<suite>/features/steps/*.py | sort | uniq -d` must be empty.
4. **dogtail 4.16** — never pass `requireResult` to `findChild`; use `findChildren(pred)` for no-raise.
5. **GNOME Shell 50+ top-bar** — use `Shell.Eval`, not AT-SPI clicks; set `unsafe_mode=true` first.
6. **Smoke suite is local, not SSH** — smoke runs inside the VM via qecore-headless; never import `tests.shared.ssh_steps` there.
7. **Behave only** — no new pytest files outside `tests/unit/`; legacy pytest was removed 2026-05.
8. **Fedora 41 for test container** — qecore/dogtail/GObject stack runs in `registry.fedoraproject.org/fedora:41`.
9. **Dry-run before push** — run `behave --dry-run tests/<suite>/features` after touching `.feature` files.
10. **Update skills in the same PR** — any code change that introduces or alters a pattern, workaround, or contract must update the matching skill file (pure refactors, helper dedups, and added coverage without new conventions are exempt). See [`skills/meta/skill-improvement/SKILL.md`](skills/meta/skill-improvement/SKILL.md).
11. **Isolated work lives in `.worktrees/<short-desc>`** — branch from `origin/main` at the repo root; never `/tmp`, `/var/tmp`, or sibling directories, and never touch another worktree's branch or working tree. See [`skills/ci-ops/contributing/references/branch-and-worktree.md`](skills/ci-ops/contributing/references/branch-and-worktree.md).

## Task → skill

| Task | Load |
|---|---|
| Writing behave scenarios / steps | [`skills/test-authoring/behave/SKILL.md`](skills/test-authoring/behave/SKILL.md) |
| GNOME Shell / AT-SPI / dogtail interactions | [`skills/test-authoring/gnome/SKILL.md`](skills/test-authoring/gnome/SKILL.md) |
| KDE/Plasma / selenium-webdriver-at-spi / Gamescope CDP | [`skills/test-authoring/kde/SKILL.md`](skills/test-authoring/kde/SKILL.md) |
| bootc upgrade / rollback / migration tests | [`skills/test-authoring/bootc/SKILL.md`](skills/test-authoring/bootc/SKILL.md) |
| UEFI/OVMF reboot testing | [`skills/test-authoring/uefi-boot/SKILL.md`](skills/test-authoring/uefi-boot/SKILL.md) |
| Variant matrix, coverage gaps, `@future` stubs | [`skills/test-authoring/suite-map/SKILL.md`](skills/test-authoring/suite-map/SKILL.md) |
| Quarantine expiry and policy | [`skills/test-authoring/quarantine-age/SKILL.md`](skills/test-authoring/quarantine-age/SKILL.md) |
| Reusable e2e workflow / consumer wiring | [`skills/ci-ops/e2e-workflow/SKILL.md`](skills/ci-ops/e2e-workflow/SKILL.md) |
| Lab gotchas (GDM, oomd, Argo, runners) | [`skills/ci-ops/ops/SKILL.md`](skills/ci-ops/ops/SKILL.md) |
| Dashboard metrics / Astro site | [`skills/ci-ops/dashboard-metrics/SKILL.md`](skills/ci-ops/dashboard-metrics/SKILL.md) |
| Contribution mechanics / PR checklist | [`skills/ci-ops/contributing/SKILL.md`](skills/ci-ops/contributing/SKILL.md) |
| Flatpak screenshot gallery (app authors) | [`skills/flatpak-screenshots/SKILL.md`](skills/flatpak-screenshots/SKILL.md) |
| When to stop and ask a human | [`skills/meta/human-gates/SKILL.md`](skills/meta/human-gates/SKILL.md) |
| Triage issues and label hygiene | [`skills/meta/triage/SKILL.md`](skills/meta/triage/SKILL.md) |
| Skill update mandate | [`skills/meta/skill-improvement/SKILL.md`](skills/meta/skill-improvement/SKILL.md) |
| How to write or maintain a skill | [`skills/meta/writing-skills/SKILL.md`](skills/meta/writing-skills/SKILL.md) |
| Operational commands (manual runs, merge queue, diagnostics) | [`runbook.md`](runbook.md) |
| Ownership boundaries between repos | [`architecture.md`](architecture.md) |
| Release-trust / audit posture | [`qa-review.md`](qa-review.md) |

## Factory contracts (upstream, do not copy here)

These are owned by `projectbluefin/common`. Read them there; testsuite links
rather than duplicates, because duplicated policy drifts.

| Contract | Source |
|---|---|
| Factory onboarding, two-output rule, banned artifacts | [`common/docs/skills/factory-onboarding.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/factory-onboarding.md) |
| Seven-label workflow | [`common/docs/skills/label-workflow.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/label-workflow.md) |
| Agentic operating model | [`common/docs/factory/agentic-model.md`](https://github.com/projectbluefin/common/blob/main/docs/factory/agentic-model.md) |
| CODEOWNERS, triagers, branch protection | [`common/docs/skills/governance.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/governance.md) |
| Human gates (factory-wide) | [`common/docs/skills/human-gates.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/human-gates.md) |

Local authority wins on repo-specific paths, build commands, ownership, and
branch targets. Upstream wins on factory-wide contracts. When the two genuinely
conflict on a factory-wide rule, stop and escalate — do not silently pick one.

## Project agents

Local agents live in `.pi/agents/`. Use them for scoped work.

| Agent | Purpose |
|---|---|
| `test-author` | Implement `@future` scenarios and fill coverage gaps |
| `triage` | Label, close duplicates, classify regressions |
| `pr-reviewer` | Review PRs against contribution gates |

## Improving these docs

Every session produces two outputs: the work, and the learning. Any session that
discovers a workaround or convention must write it back in the same PR. See
[`skills/meta/skill-improvement/SKILL.md`](skills/meta/skill-improvement/SKILL.md)
for the checklist and [`skills/meta/writing-skills/SKILL.md`](skills/meta/writing-skills/SKILL.md)
for format rules.
