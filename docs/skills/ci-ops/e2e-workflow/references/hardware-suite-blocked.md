---
name: hardware-suite-blocked
description: "Why an all-@hardware_blocked suite (`nvidia`) is reported as blocked and fails the job instead of showing a silent green pass."
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Hardware-Only Suite Blocked Backstop

`hardware`, `nvidia` and `security` are selectable `suites` values in
`.github/workflows/e2e.yml`. They are hardware-oriented groups that need real
device hardware rather than a GNOME desktop VM. This reference documents the
backstop that makes an all-blocked selection loud instead of a misleading green
pass.

## The problem

`nvidia` is the current all-blocked case: every scenario in
`tests/nvidia/features/gpu.feature` is tagged `@hardware_blocked`. On a
GPU-less GHA runner, behave runs zero scenarios for that suite and still exits
`0` -- a green pass that ran nothing. Selecting `hardware` or `security` on a
runner without the matching device produces the same silent green.

## The guard is structural, not per-suite

`scripts/suite_blocked.py` answers one question before behave runs: does the
suite contain at least one scenario that is **not** `@hardware_blocked`? It
scans the suite's feature files for the tag, so it covers `nvidia` today and
any future all-blocked group without a hard-coded name.

- Run step (after the KDE skip block):
  `python3 scripts/suite_blocked.py "tests/${SUITE_DIR}"` prints `BLOCKED` when
  every scenario is blocked and `RUNNABLE` otherwise.
- On `BLOCKED` the script writes `suite_blocked=true` to `$GITHUB_OUTPUT`,
  emits an `::error::` annotation, writes a synthetic behave result (a single
  `skipped` scenario carrying the issue #706 reason) and `exit 0`.
- The script must live inside the `Checkout testsuite` sparse-checkout block or
  it is absent at runtime.

## The fail backstop

A separate job step with `if: steps.run.outputs.suite_blocked == 'true'` runs
`exit 1` with a loud `::error::`. This makes the block fail the job rather than
stay green -- the exact mirror of the KDE `passed > 0` backstop, which fails an
all-skipped KDE run. A hardware gap is a real gap, not a test failure, but it
must never be a silent green.

## The one rule

Never re-derive blockedness from behave's exit code: behave exits `0` for a
zero-scenario run, so the run step must call `suite_blocked.py` directly.
Behaviour is locked in by `tests/unit/test_suite_blocked.py`.
