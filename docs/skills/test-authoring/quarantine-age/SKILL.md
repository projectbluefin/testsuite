---
name: quarantine-age
version: "1.0"
last_updated: "2026-07-20"
id: quarantine-age
one_line_purpose: Apply quarantine expiry policy to stale scenarios.
entry_point: docs/skills/test-authoring/quarantine-age/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [quarantine, policy, flaky]
description: "Quarantine policy and age limits for stale tests. Load when deciding whether to quarantine, unquarantine, or remove a scenario."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Quarantine age enforcement

## When to Use

- Changing `scripts/check_quarantine_age.py`
- Changing the `quarantine-age` job in `.github/workflows/pr-validate.yml`
- Debugging CI failures caused by expired `@quarantine` scenarios

## When NOT to Use

- Editing runtime skip behavior for `@quarantine` or `@pending` tags in behave hooks
- Writing or debugging the quarantined scenarios themselves
- Changing reusable VM/e2e pipeline behavior unrelated to quarantine expiry

## Core Process

1. Scan current `tests/**/*.feature` files and collect scenarios tagged `@quarantine`.
2. For each feature file, walk `git log --follow --name-only` (newest first, reversed in Python because git ignores `--follow` with `--reverse`) and inspect file snapshots with `git show <sha>:<path-at-that-commit>`.
3. Record the first commit where each scenario appears with `@quarantine`; if history cannot prove it, fall back to the file's last git modification date.
4. Calculate age in days and fail when `age_days > (--max-days + --grace-days)`.
5. Print an actionable report with feature path, scenario name, quarantine date, age, and the required next action.
6. Use `--json` only for informational consumers (for example an Actions job summary); keep default CLI mode as the enforcement path that exits non-zero on expired quarantines.

## What it does

`scripts/check_quarantine_age.py` scans current `.feature` files for `@quarantine` scenarios, walks `git log --follow` history for each feature file, and records the first commit where each scenario appears with the `@quarantine` tag.

The script fails when a quarantine age exceeds the configured threshold:

```text
effective threshold = --max-days + --grace-days
default threshold   = 30 + 0 = 30 days
CI rollout threshold = 30 + 30 = 60 days
```

JSON mode (`--json`) emits every current quarantine entry, including `days`, `quarantined_on`, `threshold_days`, and `date_source`, and always exits 0 so workflow summaries can render counts without turning a reporting call into a job failure.

## Workflow requirements

- The `quarantine-age` job lives in `.github/workflows/pr-validate.yml`.
- That job must check out the repository with `fetch-depth: 0`; shallow history breaks age detection.
- The rollout job currently runs `python3 scripts/check_quarantine_age.py --grace-days 30` to avoid blocking PRs immediately while still aging out stale quarantines.
- Any workflow using `--json` still needs full history and the full `tests/` tree checked out; otherwise age calculations and counts will be incomplete.

## Choosing the right tag when a quarantine ages out

| Situation | Tag | Required comment |
|---|---|---|
| Blocked on CI infrastructure (a masked service, unseeded state, headless session limits) | `@pending` | Name the blocker and the tracking issue |
| Covers a feature or policy that has not shipped yet, or needs a harness that does not exist | `@future` | Name the feature/harness and the tracking issue |
| The referenced upstream bug is closed | remove the tag | Note that the guard was re-activated and why |
| Genuinely flaky and under active repair | `@quarantine` | You are committing to a fix inside 30 days |

Every converted scenario keeps an explanatory comment line immediately above its tags, in the
style used by `tests/developer/features/ptyxis.feature`:

```gherkin
  # Pending: e2e.yml masks brew-setup.service, so Homebrew is never provisioned in CI (#487).
  @pending @brew_version
  Scenario: brew --version returns a version string
```

Never delete a scenario to clear the gate — the coverage intent is the asset. Never raise
`--max-days`/`--grace-days` or edit the `quarantine-age` job thresholds to clear the gate.

## Operator expectations

- If a quarantine ages out, fix the scenario or convert it to `@future`/`@pending` when it represents planned coverage rather than flaky regression coverage.
- `@quarantine`, `@pending` and `@future` are all skipped at runtime by `tests/shared/quarantine.py`, which every suite's `before_scenario` hook calls. Reclassifying a tag therefore keeps the scenario skipped rather than turning it into a failure — but only because that helper handles all three tags. Do not drop one.
- Keep the script dependency-free so it can run on `ubuntu-latest` with only checkout + Python setup.
- Prefer snapshot-based history checks (`git show <sha>:<path>`) over fragile diff hunk matching; the goal is stable CI enforcement, not perfect archeology.

## Common Rationalizations

- "A shallow checkout is enough because the script only looks at the current file."  
  It is not; age detection depends on full git history, so `fetch-depth: 0` is mandatory.
- "We should diff hunks around the scenario instead of reading historical snapshots."  
  Snapshot reads are simpler and more stable across refactors and formatting churn.
- "Grace days mean the rule is optional."  
  No; grace days are rollout padding, not a permanent exemption.

## Red Flags

- The workflow runs the script after a shallow checkout
- The script starts depending on third-party Python packages for CI
- Report output omits the remediation path (`fix it` or `convert to @future/@pending`)
- New quarantine-age behavior lands without updating this skill

## Verification

- [ ] `python3 -m ruff check tests/ scripts/ --select E,F,W --ignore E501` passes
- [ ] `python3 -m pytest tests/unit/test_quarantine_age.py tests/unit/test_quarantine.py -v` passes
- [ ] `python3 -m py_compile scripts/check_quarantine_age.py` passes
- [ ] The workflow uses SHA-pinned actions and `actions/checkout` has `fetch-depth: 0`
