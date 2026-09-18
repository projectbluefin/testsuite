---
name: contributing
version: "1.0"
last_updated: "2026-07-20"
id: contributing
one_line_purpose: Prepare, validate, and land a testsuite pull request.
entry_point: docs/skills/ci-ops/contributing/SKILL.md
category: ci-ops
mcp_compliance_level: partial
status: active
dependencies: []
tags: [contributing, pr, merge-queue, review]
description: "How to contribute changes to the testsuite repo. Load when preparing a PR or reviewing contribution mechanics."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Agent Contribution Guide

Load when: you found a bug, gap, or improvement while working in this repo.

This is an agent-first repo — agents MAY file issues and PRs directly. No human gating required.

Nightly CI is gone. PR gates are the only CI signal, and `smoke` is the standard gate suite for all consumer repos.

Unit tests temporarily stub shared modules in `sys.modules`; the unit-test
fixture restores the module table after each test so pytest-xdist workers do
not leak those stubs into unrelated test modules.

## Decision: which repo?

| Found in | Fix goes in |
|---|---|
| Feature files, step defs, qecore/dogtail patterns, shared SSH helpers | `projectbluefin/testsuite` (this repo) |
| VM specs, CronWorkflows, cluster manifests, infra | `projectbluefin/lab` |

If a fix touches both repos, split into two PRs — one per repo.

## When to contribute

Contribute when you encounter any of the following mid-task:
- A skill doc that describes wrong behavior (wrong API, stale path, incorrect command)
- A missing pattern you had to figure out from scratch (add it so the next agent doesn't)
- A new operational gotcha (failed workflow, unexpected infra behavior)
- A step that's broken or uses a deprecated API
- A coverage gap that's now worth tracking

Don't defer. File the PR as part of your current working session.

## What to update in the PR

| Change | Files to update |
|---|---|
| New scenario in any suite | Feature file + steps file |
| Scenario count changes | Run `python3 scripts/update_coverage_snapshot.py` — it regenerates the suite-map coverage snapshot. **Never hand-edit the numbers** (that is the merge-conflict root cause). Only hand-edit per-suite Notes prose in the script's `SUITE_NOTES` if a suite's purpose changed |
| New unit test file | `docs/qa-review.md` unit test table |
| New suite or variant-matrix change | `docs/skills/test-authoring/suite-map/SKILL.md` variant matrix + `docs/runbook.md` suite layout table |
| New step pattern discovered | `docs/skills/test-authoring/behave/SKILL.md` |
| New dogtail / GNOME anti-pattern | `docs/skills/test-authoring/gnome/SKILL.md` |
| New bootc JSON path or gotcha | `docs/skills/test-authoring/bootc/SKILL.md` |
| Infra gotcha (GDM, VM) | `docs/skills/ci-ops/ops/SKILL.md` |
| New hard rule for all agents | `docs/SKILL.md` (rules section) |
| e2e workflow changes (inputs, stages, image requirements) | `docs/skills/ci-ops/e2e-workflow/SKILL.md` |
| Quarantine expiry enforcement or stale `@quarantine` policy | `docs/skills/test-authoring/quarantine-age/SKILL.md` |
| Behavior or command change | `README.md` and/or `docs/runbook.md` if agent-facing docs describe the old behavior |
| @future scenario now implemented | Remove `@future` tag; update `docs/qa-review.md` + `docs/skills/test-authoring/suite-map/SKILL.md` status |
| Coverage gap resolved | Update `docs/qa-review.md` known gaps + `docs/skills/test-authoring/suite-map/SKILL.md` known gaps |
| `container/Containerfile.runner` changed | Dispatch `build-runner.yml` manually before dispatching any test run — the runner image is NOT auto-rebuilt on push; the new image must be pushed to GHCR before tests will see it |

## Improving skill docs

If a skill doc (`docs/skills/*.md`) is wrong or incomplete:

1. Edit the relevant file in `docs/skills/`
2. Branch: `docs/skills/<what-changed>`
3. In the PR description, quote the old incorrect text and explain what you found
4. No need for the scenario count section if it's docs-only

**Do not add hard rules to individual skill docs** — rules go in `docs/SKILL.md` (single source). Skill docs hold patterns and examples only.

**The skill-improvement mandate:** every PR that changes `tests/**`, `.github/workflows/**`, or `scripts/**` should include a matching skill file update. See [`docs/skills/meta/skill-improvement/SKILL.md`](../../meta/skill-improvement/SKILL.md) for what counts as a learning, which skill to update, and how to commit it together. This is a review expectation, not an automated check — no CI job enforces it.

## On-demand references

- [Branch naming and worktree policy](references/branch-and-worktree.md)
- [Working in <image-org>/actions](references/actions-repo.md)
- [PR description format](references/pr-format.md)
- [Testing your changes with the GitHub Action](references/testing-changes.md)
- [Reviewing PRs before merging](references/reviewing-and-merging.md)
