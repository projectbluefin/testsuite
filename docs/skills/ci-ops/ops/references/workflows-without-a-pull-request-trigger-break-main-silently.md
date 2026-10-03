---
name: workflows-without-a-pull-request-trigger-break-main-silently
description: "Deep dive: workflows with no pull_request trigger break main silently"
metadata:
  type: reference
  audience: agents
  maturity: stable
  context7-sources:
    - /actions/checkout
---
# Workflows Without A Pull Request Trigger Break Main Silently

## Schedule-only workflows have no PR safety net

`.github/workflows/publish-to-pages.yml` builds the dashboard and runs on `schedule`,
`push` to `main` (paths-filtered), and `workflow_dispatch` — never on `pull_request`.
Nothing validates the dashboard build while a PR is open, so a dependency bump can be
merged fully green and only fail afterwards, on a schedule tick that no human is
watching. The classic signature is an `npm ci` `ERESOLVE` peer-dependency conflict
introduced by an automated dependency-update PR: the lockfile resolves locally, the PR
checks are all unrelated, and the workflow then fails on every scheduled run until
someone happens to open the Actions tab.

**Rule: when a workflow validates an artifact that PRs can break, it needs a
PR-triggered counterpart.** Otherwise its first red run is on `main`, after the
breaking change is already merged. Either add `pull_request` (with the same paths
filter) to the workflow, or add an equivalent build job to `pr-validate.yml`. Check
this whenever you add a schedule-only or push-only workflow, and whenever you add a
new buildable artifact directory to the repo.

The corollary applies to the paths filter too: a `push`-on-`main` trigger scoped to
`dashboard/**` does not fire when the break comes from a lockfile or config file
outside that path.

## Workflows must list themselves in their paths filter

A paths filter that scopes a workflow to `container/Containerfile.runner` does not
fire when the change is to `.github/workflows/build-runner.yml` itself — the workflow
that owns the build step. The same blind spot applies to `pull_request.paths`: an
editing-only PR (for example, a docker-action SHA bump) merges fully green because
no build job ever ran. Mirror the file under `.github/workflows/` so edits to the
workflow itself are build-validated, the same way the artifact source is:

```yaml
on:
  push:
    branches: [main]
    paths:
      - container/Containerfile.runner
      - .github/workflows/build-runner.yml
  pull_request:
    branches: [main]
    paths:
      - container/Containerfile.runner
      - .github/workflows/build-runner.yml
```

`build-kde-runner.yml` already does this. `build-runner.yml` did not (issue
`#939`); the asymmetry is repaired in the same PR so the workflow now build-
validates edits to itself. The asymmetry between a workflow's inputs and its own
path is the easiest of these gaps to ship — check both lists every time you
touch `.github/workflows/**`.

## Triage: find the first failing run, not the newest merge

A schedule-only workflow can be red for many consecutive runs before it is noticed, so
the most recent merge is almost never the cause. Get the run history and find the
boundary between the last green run and the first red one, then diff the two commits:

```bash
gh run list --workflow "Publish QA Dashboard & Screenshots to Pages" \
  --limit 60 --json conclusion,createdAt,headSha,databaseId

# then diff the last green head against the first red head
git log --oneline <last-green-sha>..<first-red-sha>
```

The change that lands in that range is the breaking one. Reading the newest failing
log alone tells you the symptom but not which merge introduced it.

## Worked example: build-and-publish workflow gaining a PR trigger

The two runner-image workflows in this repo — `.github/workflows/build-runner.yml`
and `.github/workflows/build-kde-runner.yml` — build **and publish** an OCI image to
GHCR. Their only guard against a breaking base-image (Containerfile) digest bump was
`push` to `main` plus a weekly cron, so a `microdnf` step broken by a new fedora-minimal
digest surfaced only after merge. Issue #918.

The fix is two lines per workflow:

1. Add a `pull_request` trigger with the **same** paths filter as `push`:

   ```yaml
   pull_request:
     branches: [main]
     paths:
       - container/Containerfile.runner
   ```

2. Make the publish conditional so a PR validates the build without writing the
   mutable `runner` / `kde-runner` tag. Publish on everything **except** `pull_request` —
   `push` to `main`, the weekly `schedule`, and `workflow_dispatch` all publish, so a
   `github.event_name == 'push'` gate would silently stop the cron and manual publishes:

   ```yaml
   - name: Build and push
     uses: docker/build-push-action@<sha> # v7
     with:
       push: ${{ github.event_name != 'pull_request' }}
   ```

Any downstream step that consumes a publish artifact (e.g. the `Image digest` step that
echoes `steps.build.outputs.digest`) must be guarded with `if: github.event_name !=
'pull_request'` too, since no digest is produced on a build-only PR run. This is the
canonical shape of “PR-triggered counterpart” for a workflow that also publishes: build
on PR, push on everything else.

## Status

`build-runner.yml` and `build-kde-runner.yml` now both carry a `pull_request`
counterpart (issue #918). Check these two plus any new buildable-artifact workflow
against the rule above when editing `.github/workflows/`.
