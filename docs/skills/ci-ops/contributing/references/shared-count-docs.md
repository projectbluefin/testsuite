---
name: shared-count-docs
description: "Avoiding merge collisions on qa-review.md and suite-map/SKILL.md."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Shared Count Docs

Two files hold the repo-wide scenario counts:

- `docs/qa-review.md` — the mechanical recount line near the top
- `docs/skills/test-authoring/suite-map/SKILL.md` — the generated coverage snapshot block

If every scenario PR edited them, only one scenario PR could be open at a time,
and each merge would make the next one conflict. They are the repo's permanent
merge-contention hotspot, so scenario PRs stay out of them.

## The rule

- A PR that adds, removes or retags scenarios does **not** touch the generated
  block or the recount line.
- The counts are refreshed in a separate PR that changes nothing else, after
  scenario PRs have merged. Run the generator, then copy its totals into the
  `docs/qa-review.md` recount line:

  ```bash
  python3 scripts/update_coverage_snapshot.py
  ```

- Never work the numbers out by hand. Arithmetic on the previous total
  propagates any error already on `main`.
- Between refreshes the counts on `main` lag behind the feature files. That is
  expected; the `Coverage snapshot fresh` check only warns about it on `main`.

## Why "MERGEABLE" is misleading

GitHub computes mergeability against the **current base**, one PR at a time. Two
PRs that edit the same lines of either file both report MERGEABLE while the
other is unmerged. The conflict materialises the moment the first one lands.

Never treat a green mergeable badge as proof that a batch of PRs can land in any
order. Diff the shared files across the open set before queueing:

```bash
for p in <pr numbers>; do
  echo "=== $p ==="
  gh pr diff "$p" | awk '/^diff --git/{f=/qa-review|suite-map/} f&&/^[+-][^+-]/'
done
```

## Order by blast radius, largest first

Other PRs still edit these files outside the counts, for example the variant
matrix or the gap list. A PR that **restructures** either file (adds a column,
rewrites a table, replaces a section) must merge **before** PRs that only edit
rows. Reversing that order forces the restructuring PR — the larger and harder
one — to be redone against the new content.

## When you cannot merge

If you are not the one merging, **say so on the PR**: name which shared files it
touches, which open PR should land first, and that a rebase is required after.
An agent that opens a contending PR silently has handed the conflict to whoever
merges.

## Red flags

- A scenario PR whose diff touches the generated block or the recount line
- A refresh PR that also changes feature files, steps or other docs
- A count total that no generator run supports
- After a refresh PR, the recount line and the generated block disagree

## Verification

- [ ] Scenario PR: generated block and recount line unchanged
- [ ] Refresh PR: only the block and the recount line change, and
      `python3 scripts/update_coverage_snapshot.py --check` passes
- [ ] Shared-file diffs compared against every other open PR
- [ ] Merge order noted on the PR when another PR must land first
