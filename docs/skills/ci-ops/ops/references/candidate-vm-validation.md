---
name: candidate-vm-validation
description: "Change-path policy for which candidate-VM suites a testsuite PR must boot before v1 distributes it, and the audited state of today's gates (#1027)."
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Candidate-VM validation before `v1` distribution

Until #1027, `update-v1-tag.yml` force-pushed `v1` to every new `main` commit, and
consumers call `e2e.yml@v1`. A merged test or workflow change therefore reaches
consumer qualification gates without ever booting. Lint, `behave --dry-run`
and unit tests cannot prove GNOME/AT-SPI startup, runner-side SSH probes,
bootc reboots or result propagation (testsuite#1027, parent #1021).

## Change-path policy

`scripts/vm_validation_plan.py` maps changed paths to the minimal
representative `e2e.yml` suites. Rules live in its `RULES` table; tests in
`tests/unit/test_vm_validation_plan.py`.

```bash
git diff --name-only upstream/main...HEAD | python3 scripts/vm_validation_plan.py
```

| Changed path | Suites to boot |
|---|---|
| `*.md`, `docs/`, `tests/unit/`, `dashboard/`, `Justfile`, `plans/`, non-distributed workflows (`pr-validate`, `unit-tests`, `docs-validate`, `publish-to-pages`, `update-v1-tag`) | none |
| `tests/<suite>/**` (steps, hooks, features) | that suite |
| `tests/shared/kde_*` | `kde-smoke` |
| `tests/shared/extension_*`, `gnome_extensions_*` | `extensions` |
| `tests/shared/ssh_*` | `common`, `lifecycle` |
| other `tests/shared/*`, `container/` runner, `scripts/*` that `e2e.yml` runs | `smoke`, `common` |
| `.github/actions/gnome-e2e/**`, `scripts/extension_validation.py` | `gnome-e2e-action` (reported under `composite_action`, not `suites`) |
| `.github/workflows/e2e.yml`, `manual.yml` | `smoke`, `common`, `lifecycle` |
| `migration-test.yml` / `iso-*.yml` | `lifecycle` / `installer` |
| anything else | `smoke`, `common`, `lifecycle` (fail-closed) |

`smoke` is the GUI lane, `common` the SSH lane and `lifecycle` the bootc reboot
lane. Suites with no hosted `e2e.yml` lane (`hardware`, `security`, `nvidia`,
`flatcar`) are reported under `no_hosted_lane` rather than dropped — the plan
must not read as "nothing to boot" when it cannot validate them.

`e2e.yml` never calls the `gnome-e2e` composite action, and its sparse checkout
excludes `scripts/extension_validation.py`, which only the action runs. Booting
`e2e.yml` suites therefore exercises none of that code. Such changes are
reported under `composite_action` (pseudo-lane `gnome-e2e-action`), excluded
from `suites` and `no_hosted_lane`; validate them with a workflow that uses
`.github/actions/gnome-e2e` at the PR's ref.

When adding a workflow, script or shared helper, add a rule: an unmatched path
silently costs the full set, and a wrong empty rule silently skips validation.

## Running the plan against the PR's own code

Dispatch `manual.yml` **on the PR branch in the fork**. It calls the fork's
`e2e.yml` revision and passes `test_repository: ${{ github.repository }}` and
`test_ref` = the dispatched branch, so the modified workflow and tests execute,
not `main`/`v1`. Pin `image` by digest (`ghcr.io/...@sha256:...`) so the
candidate identity is immutable, and pass `test_ref` as the head SHA rather than
the branch name. Never rely on `e2e.yml`'s `test_ref: main` default for this.

## Audited signal state before the gate (2026-10-28, `main` 3e5d45ad)

- Combined commit status: no statuses at all. No ghost-lab or other external
  lab context is posted to testsuite commits, so there is no existing external
  signal to reuse or reconcile.
- Check runs on `main`: Lint & syntax, Behave dry-run, Quarantine age,
  Coverage snapshot fresh, pytest, build-and-deploy, Force-push v1 to HEAD.
  None boots a VM.
- ARC "ghost" runners ([arc-ghost-runners-local-dev-routing](arc-ghost-runners-local-dev-routing.md))
  are a local pre-push developer routing, not a PR or merge gate.

Re-check before relying on this: `gh api repos/projectbluefin/testsuite/commits/<sha>/status`
and `.../check-runs`.

## The post-merge `v1` gate (Option A, #1027)

`update-v1-tag.yml` no longer moves `v1` on every push. On a push to `main` it:

1. Plans the range `v1..main` (not just the last push, so a cancelled run's
   change is still covered) with `scripts/vm_validation_plan.py`.
2. Turns the plan into an action with `scripts/v1_gate.py`:
   - `move`: nothing reaches a VM (docs, unit tests, repo tooling).
   - `gate`: boot the planned suites through `e2e.yml` at the merged SHA,
     on `GATE_IMAGE` pinned by digest (repository variable `V1_GATE_IMAGE`,
     default `ghcr.io/projectbluefin/dakota:latest`). `v1` moves only if the
     call succeeds, which includes the #1022 `assert_passed.py` verdict.
   - `hold`: the plan needs a lane `e2e.yml` cannot boot (`composite_action`
     or `no_hosted_lane`).
3. On a hold or a failed gate, fails the run and opens (or comments on) the
   issue **"v1 tag held by the post-merge VM gate"** naming the held SHA. The
   next successful move closes it.

`lifecycle` is planned but not booted (`UNGATED_SUITES`): its upgrade
scenarios need a second, newer image to upgrade to (#706, #1023), and on one
image `bootc upgrade` is a no-op that #1039 fails on purpose. The run summary
lists it as not booted. Remove it from `UNGATED_SUITES` once #706 lands.

`e2e.yml`'s `test_ref` now defaults to `v1`, so consumers calling
`e2e.yml@v1` without a `test_ref` run the gated tests, not whatever is on
`main`.

**Emergency:** run **Update v1 tag** by hand on `main` with `force` and a
`reason`. It moves `v1` to `main` without booting and records who and why.
