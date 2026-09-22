---
name: reviewing-and-merging
description: "Detailed guidance for testsuite contributors: load when the core contributing skill routes you here."
metadata:
  type: reference
  audience: agents
  maturity: stable
---

# Reviewing PRs before merging

## Reviewing PRs before merging

Before enqueuing any PR, read the diff (`gh pr diff <N> --repo projectbluefin/testsuite`). Check:

1. **Correctness** — step names in `.feature` files have matching `@step` implementations; new steps don't duplicate existing ones.
2. **Not superseded** — compare the PR's changes against `git show origin/main:<file>` for each modified file. If the core change is already in main (landed via another PR), close the PR with a comment explaining which commit superseded it.
3. **Contributor PRs** — check `maintainerCanModify` before deciding to fix vs close:
   ```bash
   gh pr view <N> --repo projectbluefin/testsuite --json maintainerCanModify,headRepositoryOwner,headRefName
   ```
   If `maintainerCanModify: true`, check out and push fixes directly to the contributor's branch rather than opening a new PR.

### Resolving count conflicts when rebasing

PRs that update `docs/qa-review.md` or `docs/skills/test-authoring/suite-map/SKILL.md` counts frequently conflict when rebased. Resolve by recalculating from main's current counts plus the PR's delta — never blindly accept either side:

```
# Identify what the PR changes (e.g. removes 8 @quarantine tags)
# Start from main's numbers and apply the delta:
#   main:  268 total / 30 quarantined / 217 active / 21 stubs
#   PR:    removes 8 quarantine tags
#   result: 268 / 22 quarantined / 225 active / 21 stubs
```

The suite table row for the affected suite must also be updated to reflect the correct active/quarantined split.

### Merge queue dependency ordering

If PR B depends on step functions added by PR A (e.g. B's `.feature` uses `Switch to migration target` defined in A's `steps.py`), enqueue A first. The merge queue tests each entry against all preceding entries in the queue, so B will see A's steps in CI even before A merges to `main`.

Corollary: do not close or skip enqueuing a "dependency" PR just because its CI ran against an older `main` — re-enqueue both in order.

## Merging PRs — the effective gate

**The gate to apply:**

1. **GitHub Actions CI green** — the five required checks below.
2. **Human approval to merge.** Merging is a human gate; an agent prepares the
   PR and asks. See `docs/skills/meta/human-gates/SKILL.md`.
| Check | Workflow | Trigger |
|---|---|---|
| `Lint & syntax` | `pr-validate.yml` | `pull_request`, `merge_group`, `push: main` |
| `Behave dry-run` | `pr-validate.yml` | same |
| `Quarantine age` | `pr-validate.yml` | same |
| `pytest` | `unit-tests.yml` | `pull_request`, `merge_group`, `push: main` |
| `docs-validate` | `docs-validate.yml` | `pull_request`, `merge_group`, `push: main` |

These are the required status checks configured on the `main — merge queue`
repository **ruleset** (which also enables the merge queue, squash method, and
`ALLGREEN` grouping). `gh api repos/projectbluefin/testsuite/branches/main/protection`
returns `404 Branch not protected` — expected, because the configuration lives
in a ruleset. Verify with `gh api repos/projectbluefin/testsuite/rulesets`.

Once CI is green and a human has approved, enqueue with:

```bash
gh pr merge <NUMBER> --repo projectbluefin/testsuite --squash --auto
```

The `--auto` flag enqueues the PR; the merge queue re-runs the required checks
on the merge commit and lands to `main` automatically on green. Do not attempt
`--admin` bypasses.

**Counted-evidence rule for token plumbing.** Token-like strings are redacted in
command and log output, so you can never confirm an `Authorization` header by
reading it — a working header and an uninterpolated placeholder look identical.
Compare occurrence counts against a known-working file instead:

```bash
grep -c GITHUB_TOKEN <template>.yaml   # must match the working reporter's count
```

A template that defines the token but never interpolates it into the request
shows a lower count than the reference. Counts survive redaction; rendered text
does not.

## Dependency updates (Renovate / mergeraptor)

Dependency updates for this repo and `projectbluefin/bluefin` are managed by Renovate (bot login: `app/mergeraptor`). No manual action is required from agents.

**Automerge policy (configured in `renovate.json`):**

| Update type | Action |
|---|---|
| `digest`, `pin`, `patch`, `minor` | Automerged when CI passes (squash) |
| `major` | Opens a PR — requires manual review |

**Triggering Renovate manually** (e.g. after config changes):

1. Open the [Dependency Dashboard](https://github.com/projectbluefin/testsuite/issues) issue (titled "Dependency Dashboard")
2. Check the **"rebase all open PRs"** checkbox — Renovate will pick up the updated config and rebase all open dep PRs

Or edit the checkbox directly via gh:
```bash
gh issue view <dashboard-issue-number> --repo projectbluefin/testsuite --json body --jq '.body' | \
  sed 's/ - \[ \] <!-- rebase-all-open-prs -->/ - [x] <!-- rebase-all-open-prs -->/' | \
  gh issue edit <dashboard-issue-number> --repo projectbluefin/testsuite --body-file -
```

**bluefin-specific:** `renovate.json` in `projectbluefin/bluefin` sets `"baseBranches": ["testing"]` — all Renovate PRs there target the `testing` branch, not `main`.

## After the PR merges

- If you changed `docs/qa-review.md`, verify the scenario count is still accurate
- If you resolved a `@future` scenario, confirm `just list-stubs` no longer lists it
- If you added a new operational gotcha to `docs/skills/ci-ops/ops/SKILL.md`, check `docs/SKILL.md`'s rules section doesn't already cover it (avoid duplication)
