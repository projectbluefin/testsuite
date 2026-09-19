---
name: migration-inputs
description: "Why e2e.yml must declare the migration-target and extra-tags inputs that migration-test.yml passes, and the four places the wiring lives."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# `e2e.yml` migration inputs: `migration-target` and `extra-tags`

`migration-test.yml` calls `e2e.yml` and passes two inputs that `e2e.yml` must
declare, or GitHub rejects the `workflow_call` at startup — `startup_failure`,
zero jobs, no logs to read. That is exactly what broke the `@migration` lane
when a stale-branch merge dropped the declarations but left the caller intact.

## The inputs

| `e2e.yml` input | Passed as | Effect |
|---|---|---|
| `migration-target` | `MIGRATION_TARGET` env var (local `lifecycle` behave branch only) | Target image ref for cross-registry migration. Empty → `tests/lifecycle/features/steps/steps.py` falls back to `ghcr.io/projectbluefin/bluefin:stable`. |
| `extra-tags` | appended to `BEHAVE_TAG_ARGS` as `--tags <value>` (only when non-empty) | Scopes the run, e.g. `migration` runs only `@migration` scenarios instead of the whole lifecycle suite. |

## The wiring moves as one unit

All four parts must be present together:

1. The two input declarations under `workflow_call.inputs`.
2. The `MIGRATION_TARGET` / `EXTRA_TAGS` entries in the `Run behave suite` job `env`.
3. The `[[ -n "${EXTRA_TAGS}" ]] && BEHAVE_TAG_ARGS="... --tags ${EXTRA_TAGS}"` line in the tag filter.
4. The `MIGRATION_TARGET="${MIGRATION_TARGET}"` assignment on the local behave invocation.

The KDE-container branch deliberately does not run `@migration` and is left
alone.

The test code reads `MIGRATION_TARGET` in `tests/lifecycle/features/steps/steps.py`,
and `migration.feature` / `homed_migration.feature` document it, so the env var
is a hard expectation, not optional.

## Red flag

A diff that removes — or fails to declare — these inputs while
`migration-test.yml` still passes them reproduces the `startup_failure`. The
failure is silent from the caller's point of view: the run shows zero jobs
rather than a failing step, so it reads as infrastructure flake rather than a
workflow-contract break.

If you touch the migration env plumbing, verify that the caller
(`migration-test.yml`) and the test code still expect the same names before
merging.
