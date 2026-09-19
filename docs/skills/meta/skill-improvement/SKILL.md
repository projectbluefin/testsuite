---
name: skill-improvement
version: "1.0"
last_updated: "2026-07-20"
id: skill-improvement
one_line_purpose: Capture durable agent learnings in maintained skill docs.
entry_point: docs/skills/meta/skill-improvement/SKILL.md
category: meta
mcp_compliance_level: partial
status: active
dependencies: []
tags: [skills, learning, factory]
description: "The self-improvement loop: when and how to write a skill update for a code change. Load when you changed tests, workflows, actions, or scripts."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Skill Improvement Mandate

Every agent session that changes this repo produces two outputs:

1. **The work** — the PR, fix, or test coverage improvement
2. **The learning** — what a future agent should know

Output 1 without Output 2 leaves the factory no smarter. The loop only compounds if agents write back.

This is the factory-wide two-output rule; the canonical statement lives in
[`common/docs/skills/factory-onboarding.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/factory-onboarding.md).
This file covers what is specific to testsuite.

**Banned artifacts — delete on sight:** changelog files (`CHANGELOG.md`,
`IMPROVEMENTS.md`, `SESSION.md`), committed session logs and plan files
(`NOTES.md`, `PLAN.md`, `TODO.md`, `plans/*.md`), and any doc instructing you to
"append here". Route the content to the matching `docs/skills/**` file instead.
`plans/*.fmf` are TMT/fmf test metadata, not session logs — leave them.

## Before You Mark Work Complete

Run this checklist before enqueuing any PR:

- [ ] Did I introduce or alter any workaround, non-obvious pattern, or contract?
- [ ] If no — the skill-update gate is satisfied (pure refactoring, helper deduplication, and added coverage without new conventions are exempt).
- [ ] If yes — is there a skill file for the area I worked in?
- [ ] If yes — did I update it?
- [ ] If no — did I create one in `docs/skills/<category>/<area>/SKILL.md` or update the closest matching skill?
- [ ] Is the skill file committed in **this same PR**? (Not a follow-up. Same PR.)

If applicable and all items are checked, you're done. If any required item is unchecked, finish it first.

No CI job enforces this. The skill-drift check was retired in #681; the mandate is enforced during PR review. Reviewers reject PRs that change `tests/**`, `.github/workflows/**`, `.github/actions/**`, or `scripts/**` AND introduce or alter a pattern, workaround, or contract without a matching skill update. Pure refactoring, helper deduplication, and added test coverage that introduce no new conventions are exempt.

## What Counts as a Learning Worth Writing Back

**Write it:**

| Category | Example |
|---|---|
| Upstream bug workaround | "GNOME 50 removed `list item` role in Nautilus sidebar — use `button` role instead" |
| Non-obvious correctness requirement | "behave dry-run must pass before pushing — CI runs it in a Fedora 41 container with the full dogtail stack" |
| Convention not obvious from code | "Smoke suite uses subprocess, not SSH — never import `tests.shared.ssh_steps` into smoke environment" |
| Trial-and-error discovery | "dogtail 4.16 removed `requireResult` from `findChild` — use `findChildren(pred)` for no-raise behavior" |
| AT-SPI / GNOME version quirk | "Shell.Eval check via D-Bus requires `unsafe_mode=true` — set before any Shell.Eval call" |

**Do NOT write:**

| Category | Example |
|---|---|
| One-off task note | "Use commit message `fix(smoke): revert sidebar step` for this PR" |
| Obvious developer knowledge | "Run git status to see changed files" |
| Ephemeral state | "bazzite extensions are currently all in ERROR state due to upstream regression" |
| Contradiction of another skill | Update the skill to reflect the new reality — don't add a competing note |
| Pure refactor, dedup, or coverage | "Folded two copies of private helper into shared" or "Added unit coverage for capture path" — exempt unless introducing a new pattern or contract |

## Where to Write It

| Working in... | Write to |
|---|---|
| `tests/smoke/**` | `docs/skills/test-authoring/gnome/SKILL.md` (AT-SPI patterns) or `docs/skills/test-authoring/behave/SKILL.md` (step structure) |
| `tests/lifecycle/**` | `docs/skills/test-authoring/bootc/SKILL.md` |
| `tests/shared/**` | `docs/skills/test-authoring/behave/SKILL.md` (shared helper patterns) |
| `.github/workflows/**` | `docs/skills/ci-ops/e2e-workflow/SKILL.md` or `docs/skills/test-authoring/suite-map/SKILL.md` |
| `.github/actions/**` | `docs/skills/ci-ops/e2e-workflow/SKILL.md` |
| `scripts/**` | `docs/skills/ci-ops/e2e-workflow/SKILL.md` |
| New domain entirely | Create `docs/skills/<category>/<area>/SKILL.md`, then run `python3 scripts/generate_skill_index.py` |
| Cross-cutting (affects `projectbluefin/testsuite` + other repos) | Update local skill first, then open a propagation issue in `projectbluefin/actions` |

## Which Skill File to Update

| Changed area | Update this skill |
|---|---|
| GNOME AT-SPI step, dogtail pattern | `gnome.md` |
| behave scaffolding, step structure, shared helpers | `behave.md` |
| bootc upgrade / rollback / migration | `bootc.md` |
| e2e workflow inputs, QEMU pipeline, reusable action | `e2e-workflow.md` |
| Suite coverage, variant matrix, @future gaps | `suite-map.md` |
| VM boot, GDM, Argo, systemd-oomd, infra gotcha | `ops.md` |
| UEFI boot, OVMF, systemd-boot | `uefi-boot.md` |
| PR process, merge queue, Renovate | `contributing.md` |
| Hard rules for all agents | `docs/SKILL.md` (rules section only) |
| Skill file format, skill update mandate | `skill-improvement.md` (this file) |

When in doubt, update the closest existing skill rather than creating a new file.

## How to Commit It

The skill update goes in the **same commit or same PR** as the implementation. Not a follow-up PR.

```bash
# Stage both the implementation and the skill update together
git add tests/smoke/features/steps/gnome_files_steps.py docs/skills/test-authoring/gnome/SKILL.md
git commit -m "feat(smoke): add Nautilus sidebar navigation steps

Update gnome.md: document GNOME 50 sidebar item role change
(list item → button) and URI fallback pattern for AT-SPI action failures.

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Nothing in CI will catch a missing skill update — reviewers will. Reviewers enforce this gate before enqueuing for any PR that introduces or alters a pattern, workaround, or contract (pure refactoring, helper deduplication, and added coverage without new conventions are exempt). The path mapping above is the full contract.
