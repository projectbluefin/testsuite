---
name: human-gates
version: "1.0"
last_updated: "2026-07-29"
id: human-gates
one_line_purpose: Decide when to stop for Design, Security, Breakage, or Merge review.
entry_point: docs/skills/meta/human-gates/SKILL.md
category: meta
mcp_compliance_level: partial
status: active
dependencies: []
tags: [gates, governance, escalation]
description: "When to stop and ask a human for input. Use when a PR is ready to merge, when changing CI interfaces or secrets, when a change may break consumers, or before any upstream write."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Human Decision Gates

Four situations require stopping and requesting human input. Never guess past them.

| Gate | Stop when |
|---|---|
| **Design** | Architecture change, new test infrastructure, user-visible CI behavior change, changing what suites an image runs |
| **Security** | Secrets in CI, cosign/signing changes, any `ublue-os/*` interaction, any KDE property interaction beyond read-only, COPR sources in runner |
| **Breakage** | Removing or renaming a reusable workflow input that consuming repos depend on (e2e.yml inputs, action inputs) |
| **Merge** | PR is ready — requires GHA CI green + human approval |

---

## Design gate — examples

Stop before acting on any of these:

- Adding a new test suite (new directory under `tests/`) — affects the variant matrix, runner image, and coverage docs
- Changing which suites run for a given image in the variant matrix — affects coverage expectations for that image
- Changing the `e2e.yml` reusable workflow interface (adding/removing inputs, changing defaults) — consuming repos call this workflow
- Migrating from one test tool to another (e.g. adding playwright alongside behave)
- Adding a new QEMU boot mode or VM configuration

**Signal:** open an issue with `kind/design` label; describe the proposed change and ask for approval.

---

## Security gate — examples

Stop before acting on any of these:

- Adding `secrets:` to any workflow or composite action
- Changing cosign signing steps or supply chain verification
- Adding a new third-party composite action not already in the repo
- Changing `permissions:` blocks to grant write access beyond `contents: read` + `packages: write`
- Any change that could affect the runner container's trust boundary

**Signal:** stop immediately, describe what you found, and ask the human to review before proceeding.

---

## Breakage gate — examples

Stop before acting on any of these:

- Removing an input from `e2e.yml` that `projectbluefin/bluefin`, `projectbluefin/actions`, or other repos pass in their workflows
- Renaming the `suites` input or changing its format
- Changing the artifact schema output by `e2e.yml` (artifact names, JSON structure)
- Modifying the `gnome-e2e` composite action interface

**How to check:** search for callers before removing anything:
```bash
gh search code "testsuite/.github/workflows/e2e.yml" --repo projectbluefin --json repository,path
```

**Signal:** open a breakage issue listing every affected repo before making the change.

---

## Merge gate

**The gate to apply:**

1. **GitHub Actions CI green** — `Lint & syntax`, `Behave dry-run`,
   `Quarantine age` (`pr-validate.yml`), `pytest` (`unit-tests.yml`),
   `docs-validate` (`docs-validate.yml`). These are the required checks on the
   `main — merge queue` **ruleset**, which also enables the merge queue, squash
   method, and `ALLGREEN` grouping. `gh api
   repos/projectbluefin/testsuite/branches/main/protection` returning
   `404 Branch not protected` is expected — the configuration is a ruleset, not
   legacy branch protection.
2. **Human approval to merge.** Prepare the PR, then ask; do not merge on your
   own judgement.

Once CI is green and a human has approved, enqueue via:
```bash
gh pr merge <NUMBER> --repo projectbluefin/testsuite --squash --auto
```

The merge queue re-runs the required GHA checks on the merge commit and lands
automatically on green. Human `lgtm` is not required for normal test/docs/fix
PRs — only for:

- PRs touching `.github/workflows/e2e.yml` (reusable workflow interface)
- PRs touching `AGENTS.md` (behavioral directive changes)
- PRs touching `CODEOWNERS`

Ordering and mechanics:
[`docs/skills/ci-ops/contributing/references/reviewing-and-merging.md`](../../ci-ops/contributing/references/reviewing-and-merging.md).
---

## Upstream namespace prohibition (read-only)

**NEVER** create issues, PRs, comments, forks, or any other programmatic write to any
`ublue-os/*` repository. Read-only `gh api` calls are permitted. If a task requires
writing to `ublue-os`, stop and tell the human to report it manually.

### `projectbluefin/common` — issues only

`projectbluefin/common` is a sibling factory repo, not a read-only upstream. You
MAY file an issue there to report a factory-wide learning or a needed contract
change — that is the escalation path `AGENTS.md` prescribes. You MAY NOT push
branches, open PRs, or edit files there: a change to `common` is a human
decision gate. Report it, do not make it.

### KDE properties — strictly read-only, no exceptions

All KDE-owned properties are read-only for every agent and every automated process:

- `invent.kde.org` (GitLab) and `invent-registry.kde.org`
- `bugs.kde.org`, `discuss.kde.org`, `community.kde.org`
- KDE Matrix rooms (`#kde-qa:kde.org`, `#plasma:kde.org`, `#kde-linux:kde.org`) and mailing lists
- The `KDE/*` GitHub mirrors

**Permitted:** read-only HTTP GET, read-only API calls, `git clone`, `git fetch`, reading source
and documentation.

**Forbidden — no exceptions, and no "draft it for review" carve-out:**

- Creating or editing issues, merge requests, pull requests, comments, reviews, snippets, wiki
  pages, forks, branches, tags, or releases
- Any authenticated write, push, or `POST`/`PUT`/`PATCH`/`DELETE` to a KDE host
- Posting to KDE Matrix rooms, forums, mailing lists, or bug trackers
- Registering accounts or requesting access

This applies to sub-agents, background agents, and scheduled jobs, not only the primary session.
When work identifies a genuine upstream contribution, **produce the patch or report locally and
hand it to a human to submit.** Describe it as a recommendation, never as an action taken or
authorized.

Rationale: KDE is an upstream community this project actively wants to collaborate with. A
single unauthorized automated write would cost more trust than any test contribution could earn.

---

## Red Flags

Stop if you catch yourself doing any of these:

- Merging your own PR without an explicit human approval, or reaching for `--admin` to bypass the queue.
- Concluding `main` is unprotected because `branches/main/protection` returns 404 — the rules live in a ruleset.
- Copying live state (PR numbers, dates, current status) into a skill file instead of the tracking issue.
- Opening an issue, PR, comment, or fork in `ublue-os/*` or any KDE property "just as a draft".
- Removing an `e2e.yml` input without searching for callers first.

## Verification

Before asking for merge approval, confirm each of these:

```bash
gh pr checks <N> --repo projectbluefin/testsuite          # Lint & syntax, Behave dry-run, pytest all pass
gh pr diff  <N> --repo projectbluefin/testsuite           # no secrets, no permissions widening, no e2e.yml input removal
```

- Touches `e2e.yml`, `AGENTS.md`, or `CODEOWNERS`? A human `lgtm` is recorded on the PR.
