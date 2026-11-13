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
| `iso-*.yml` | `lifecycle` / `installer` |
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

Every pull request runs this plan automatically (`pr-vm-check.yml`, "PR VM
check"): it diffs GitHub's merge commit against its first parent and uses the
planner's `--pr` mode. That mode routes the GNOME OS canary's workflow, harness,
helper and suite to the canary rather than Dakota, and runs the canary for the
`gnome-e2e` composite action too, under the same coverage rule as the `v1` gate
below (one `canary` output from `scripts/v1_gate.py`; changed action steps the
canary skips still hold). The PR workflow itself also selects the canary so
changes to its routing exercise it.

The PR check boots planned `e2e.yml` suites on `dakota:testing` pinned by digest
at the merge commit. Other `no_hosted_lane` suites still produce a notice and
need their own hardware or a hand check. A fork PR's token is read-only, so
`e2e.yml`'s screenshot push (continue-on-error) is skipped there.

For a canary re-run, dispatch `gnomeos-canary.yml` from `main` with `test_ref`
set to the PR head commit. A fork PR head need not be pushed to a repository
branch first (issue #1172). Use a manual `e2e.yml` run (below) for another
image; it cannot cover the canary.

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
   change is still covered) with `scripts/vm_validation_plan.py`. First,
   `scripts/v1_gate_pins.py` drops any file under `.github/actions/gnome-e2e/`
   whose whole diff in the range only swaps one pinned commit SHA for another
   in `uses:` lines (Renovate's `projectbluefin/actions` digest bumps). Those
   used to hold `v1` every time (#1127, #1140). Any other change in the file,
   or a ref that is not a full SHA on both sides, keeps it in the plan. The run
   summary lists the dropped files. This is the gate's version of the hive's
   pin-only rule. The gate can now run the canary (below), but pin-only
   bumps still skip it: nothing they change needs a 15-minute GNOME OS boot.
2. Turns the plan into an action with `scripts/v1_gate.py`:
   - `move`: nothing reaches a VM (docs, unit tests, repo tooling).
   - `gate`: boot the planned suites through `e2e.yml` at the merged SHA,
     on `GATE_IMAGE` pinned by digest (repository variable `V1_GATE_IMAGE`,
     default `ghcr.io/projectbluefin/dakota:testing`). `v1` moves if the
     call succeeds, which includes the #1022 `assert_passed.py` verdict.
     If it fails, the same suites boot again with the tests at the current
     `v1` on the same digest (the baseline), and
     `scripts/v1_gate_compare.py` moves `v1` only when every failing
     scenario also fails at `v1`. A new failing scenario, a suite that
     failed without a failing scenario recorded, or a missing baseline
     holds `v1`. The gate catches testsuite regressions, not image bugs.
   - `canary`: every lane `e2e.yml` cannot boot is one the canary runs: the
     `gnome-e2e` action itself (`.github/actions/gnome-e2e/`),
     `scripts/extension_validation.py` (the action runs it for the canary
     suite), or the canary's own suite (`tests/gnomeos-canary/`). The gate calls
     `gnomeos-canary.yml` at the merged SHA, which drives that action end to
     end, and moves `v1` only if it passes. With suites to boot as well, the
     action is `gate` with `canary=true` and both must pass. Before this, each
     such change held `v1` until a maintainer ran the canary by hand and
     forced the move (#1140, #1188).
   - `hold`: the plan needs a lane neither can cover. That is an action-lane
     script the canary does not run (`scripts/assert_passed.py`: its action
     step skips the canary suite), a changed action step whose `if:` excludes
     the canary suite (`scripts/v1_gate_canary_scope.py` lists them; the run
     summary names them), or a `no_hosted_lane` suite. The hold is flagged for
     a maintainer at once. The step check does not split suite branches inside
     a shell step the canary does run.
3. On a hold or a failed gate, fails the run and opens (or comments on) the
   issue **"v1 tag held by the post-merge VM gate"** naming the held SHA. The
   next successful move closes it. Three holds are a maintainer's problem
   rather than contributor work, so the comment starts with **Needs a
   maintainer**, and the issue gets `needs-human` (and loses
   `good first issue` / `help wanted`):
   - a `hold` action: only a hand check and a forced run can release it, and
     it repeats on every push until then (#1149);
   - no failed suite produced test results on either side
     (`v1_gate_compare.py` prints `infrastructure=true`): the test machines
     most likely never booted, as when `ubuntu-latest` moved to 26.04 (#1123).
     Also `priority/critical-urgent`;
   - the issue has been open for more than 24 hours. Also
     `priority/critical-urgent`.
4. Files the failures it let through. A scenario that fails at both the
   merged SHA and `v1` comes from the image or the VM, so it never holds
   `v1`, but it keeps every later run red (the PR VM check included) until
   someone deals with it. The step "File pre-existing failures" runs
   `scripts/v1_gate_preexisting.py` on the `--preexisting` output of
   `v1_gate_compare.py` and opens one issue per scenario, titled
   `e2e: <suite> fails on <image>, also at v1: <Feature> :: <Scenario>`,
   labelled `kind/bug` and `triage/accepted`, for the hive to skip in VMs,
   quarantine or fix. It files a title only when no open issue has it, so a
   failure seen on every run is filed once. More than five at once becomes one
   issue, `e2e: many scenarios fail on <image>, also at v1`, labelled
   `needs-human`: that many points at the image as a whole. The step runs
   after a hold too, and never fails the run. Before this, #1143 and #1153
   were found by hand.

`lifecycle` is planned but not booted (`UNGATED_SUITES`): its upgrade
scenarios need a second, newer image to upgrade to (#706, #1023), and on one
image `bootc upgrade` is a no-op that #1039 fails on purpose. The run summary
lists it as not booted. Remove it from `UNGATED_SUITES` once #706 lands.

`e2e.yml`'s `test_ref` now defaults to `v1`, so consumers calling
`e2e.yml@v1` without a `test_ref` run the gated tests, not whatever is on
`main`.

**Emergency:** run **Update v1 tag** by hand on `main` with `force` and a
`reason`. It moves `v1` to `main` without booting and records who and why.
