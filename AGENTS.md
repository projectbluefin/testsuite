# testsuite — Agent instructions

You are an agent working in **testsuite**, the GNOME bootc image end-to-end test repository. This repo owns the behave/qecore/dogtail test suites, shared helpers, and reusable GitHub Actions used to validate GNOME-based bootc images.

This file is the local authority for paths, ownership, build commands, and
branch targets. `projectbluefin/common` is the pinned shared-contract sidecar for
factory-wide rules; it never overrides local authority, and local rules never
override a factory-wide contract.

## Start here

1. Read [`docs/SKILL.md`](docs/SKILL.md) next. It is the task → skill router and
   carries the hard rules. The generated catalog is `docs/skills/index.json`
   (human mirror: `docs/skills/index.md`).
2. Load only the skill file(s) matching your current task. Do not read every skill.
3. Before using any library (qecore, dogtail, behave, gi.repository, AT-SPI), look up its current docs via Context7.
4. Verify the repository, issue, branch target, and requested scope before editing.
   Work only on an issue routed to you by assignment or `3-clanker-queue`.

## Build / test / lint commands

Run these before every change:

```bash
# Lint
ruff check tests/ --select E,F,W --ignore E501

# BDD dry-run (run only if you touched .feature files)
behave --dry-run tests/<suite>/features

# Unit tests
python3 -m pytest tests/unit/ -q

# Docs + skill catalog
python3 scripts/validate_docs.py
python3 scripts/generate_skill_index.py --check

# List unimplemented scenarios
just list-stubs
```

## Navigation quick-reference

Full router: [`docs/SKILL.md`](docs/SKILL.md). Most-used entries:

| Task | Load |
|---|---|
| Writing behave tests or step definitions | `docs/skills/test-authoring/behave/SKILL.md` |
| GNOME Shell / AT-SPI / dogtail interactions | `docs/skills/test-authoring/gnome/SKILL.md` |
| bootc upgrade/rollback/migration tests | `docs/skills/test-authoring/bootc/SKILL.md` |
| UEFI/OVMF reboot testing | `docs/skills/test-authoring/uefi-boot/SKILL.md` |
| Reusable e2e workflow inputs and debugging | `docs/skills/ci-ops/e2e-workflow/SKILL.md` |
| Lab/infra gotchas (GDM, oomd, Argo mutex) | `docs/skills/ci-ops/ops/SKILL.md` |
| Coverage matrix and @future gaps | `docs/skills/test-authoring/suite-map/SKILL.md` |
| Writing or updating a skill file | `docs/skills/meta/writing-skills/SKILL.md` |
| Knowing when to stop and ask a human | `docs/skills/meta/human-gates/SKILL.md` |
| Operational commands (manual runs, merge queue, diagnostics) | `docs/runbook.md` |
| Release-trust / audit posture | `docs/qa-review.md` |
| Update cadence / promotion-gate design (research #431) | `docs/update-cadence-research.md` |

## Self-improvement

Every session produces **two outputs**: the work (PR, fix, coverage) and the
learning (what a future agent needs to know). Output 1 without Output 2 leaves
the factory no smarter. The learning goes in `docs/skills/` — **same PR, not a
follow-up**.

Banned in this repo — delete on sight:

- No changelog files (`CHANGELOG.md`, `IMPROVEMENTS.md`, `SESSION.md`).
- No session notes, plan files, or progress logs committed to the repo
  (`NOTES.md`, `PLAN.md`, `TODO.md`, `plans/*.md`). Session state lives in the
  agent's session folder only. `plans/*.fmf` are TMT/fmf test metadata and are
  **not** session logs — leave them.
- No "append here" docs. Route the learning to the matching `docs/skills/**`
  file instead.

Before marking work done:

- [ ] Discovered a workaround, pattern, or convention?
- [ ] Skill file updated (or created)?
- [ ] Committed in this same PR?

## Every-loop self-repair

Self-repair is part of every task loop, not an incident-only activity:

1. **Preflight** — verify repository, issue, catalog refs, branch target, loaded skills.
2. **Detect** — treat stale, contradictory, missing, or failed guidance as a repair signal; never silently fall back.
3. **Repair** — update the closest authoritative skill when the fix is safe, in scope, and source-backed.
4. **Validate** — rerun the smallest relevant checks; regenerate `docs/skills/index.json` if any skill front matter changed.
5. **Write back** — record durable learning and evidence in the PR body.
6. **Escalate** — stop for design, security, cross-repository breakage, merge, or production decisions. Autonomy repairs known failures; it does not manufacture approval.

Red flags: wrong-repository edits, stale catalog use, silent fallback, repeated
failure without a skill update, undocumented workarounds, and a task that ends
without evidence or durable learning.

## Factory contracts

These are owned upstream. Read them there; do not copy them into this repo,
because duplicated policy drifts.

| Contract | Source |
|---|---|
| Factory onboarding and the two-output rule | [`common/docs/skills/factory-onboarding.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/factory-onboarding.md) |
| Seven-label workflow | [`common/docs/skills/label-workflow.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/label-workflow.md) |
| Agentic operating model | [`common/docs/factory/agentic-model.md`](https://github.com/projectbluefin/common/blob/main/docs/factory/agentic-model.md) |
| CODEOWNERS, triagers, branch protection | [`common/docs/skills/governance.md`](https://github.com/projectbluefin/common/blob/main/docs/skills/governance.md) |

Factory-wide learning → open an issue in `projectbluefin/common` describing the
learning, affected component, and evidence. Filing that issue is the only write
you may make to `projectbluefin/common`: never push branches, open PRs, or edit
files there. Never write to `ublue-os/*` or any KDE property at all.

## Hard boundaries

- **Test content → this repo.** Infrastructure (VM specs, KubeVirt manifests, workflow orchestration) belongs in the separate [`projectbluefin/lab`](https://github.com/projectbluefin/lab) repo. Split PRs that touch both.
- **Never create issues, PRs, comments, forks, or writes in read-only upstream namespaces.** Read-only API calls are allowed; see `docs/skills/meta/human-gates/SKILL.md` for the prohibition details. **This explicitly includes all KDE properties (`invent.kde.org`, `bugs.kde.org`, KDE Matrix rooms, `KDE/*` mirrors) — read-only, no exceptions, for sub-agents and scheduled jobs too.**
- **Workflow action references must be pinned.** External `uses:` must be a full commit SHA with a version comment. Never use floating tags.
- **No WIP PRs.** Every open PR must be ready to merge: green CI, complete scope, no placeholder commits.
- **Concurrent PRs must own disjoint files.** There is no cap on how many PRs
  you may have open. The real constraint is conflict, not count: before opening
  a PR, check that no other open PR already touches the files you are about to
  change.

  ```bash
  gh pr list --repo projectbluefin/testsuite --state open --json number,files \
    --jq '.[] | {number, files: [.files[].path]}'
  ```

  If your file set overlaps an open PR, either fold your change into that PR or
  wait for it to land. Overlapping PRs are the thing that actually costs review
  time and creates merge-queue churn.
- **All isolated work happens in `.worktrees/<short-desc>` at the repo root**, branched from `origin/main` — never in `/tmp`, `/var/tmp`, or sibling directories. Every agent that commits gets its own worktree, and must not touch another worktree's branch or working tree. Remove the worktree and prune after the PR merges. See [`docs/skills/ci-ops/contributing/references/branch-and-worktree.md`](docs/skills/ci-ops/contributing/references/branch-and-worktree.md).
- **Merge through the merge queue with green CI.** Never `--admin`, never self-merge.

## Mandatory gates before enqueuing any PR

- [ ] `ruff check tests/ --select E,F,W --ignore E501` passes.
- [ ] `behave --dry-run` passes if any `.feature` file changed.
- [ ] `python3 -m pytest tests/unit/ -q` passes.
- [ ] `python3 scripts/validate_docs.py` passes.
- [ ] `python3 scripts/generate_skill_index.py --check` passes (regenerate with `python3 scripts/generate_skill_index.py` if you changed any skill front matter).
- [ ] No open PR touches the same files as this one (see the disjointness rule above).
- [ ] A matching skill file in `docs/skills/` is updated in the same PR if you changed `tests/**`, `.github/workflows/**`, `.github/actions/**`, or `scripts/**` AND the change introduces or alters a pattern, workaround, or contract (pure refactoring, helper deduplication, and added coverage without new conventions are exempt). If no existing skill file covers the area, update the closest matching skill or create one under `docs/skills/<area>/SKILL.md`.
- [ ] If scenario totals changed, run `python3 scripts/update_coverage_snapshot.py` to regenerate the suite-map coverage snapshot. **Never hand-edit the count numbers** — CI (`Coverage snapshot fresh` check) fails if the generated block is stale. Only hand-edit per-suite Notes prose in the script's `SUITE_NOTES`.
- [ ] PR title follows Conventional Commits (`feat`, `fix`, `docs`, `ci`, `refactor`, `test`, `build`, `chore`).
- [ ] Every AI-authored commit includes both attribution trailers:

```text
Assisted-by: <Model> via <runtime>
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

## Human decision gates

Stop and request human input when you are:

- Creating a new suite or changing CI interfaces/inputs.
- Touching secrets in CI, cosign, new third-party actions, or expanded `permissions:`.
- Removing or renaming `e2e.yml` inputs that downstream repos depend on.
- Ready to merge (always use merge queue + green CI).
- Changing repository labels, `CODEOWNERS`, branch protection, or CI `permissions:`.
- Anything that would require a change in `projectbluefin/common` — report it, do not make it.

See `docs/skills/meta/human-gates/SKILL.md` for full examples.
