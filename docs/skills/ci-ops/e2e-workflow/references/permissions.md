---
name: permissions
description: "Permission and runtime constraints when calling the reusable action."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Permissions

## Consumer constraints — what you cannot do from the reusable action

When calling this workflow from another repo, the following are explicitly banned:

- **No RPM installs** — do not add `dnf install` or `rpm -i` steps to consumer workflows or to the action inputs (`setup_script`). The test VM is a fully-baked bootc image; package mutations break repeatability and may conflict with the image's ostree deployment. Use Flatpak installs or pre-bake packages into the image.
- **No `apt install` in test steps** — the GHA runner uses `ubuntu-latest` for QEMU hosting only; apt installs in test steps (as opposed to the infrastructure setup) are not permitted.
- **No VM tuning inputs** — do not request inputs for CPU/RAM/kernel params. The pipeline runs on GitHub-hosted runners; the VM spec is fixed.
## GHCR screenshot push — cross-repo token scope

**Symptom:** `e2e.yml` "Push desktop screenshot to GHCR" step silently succeeds (exit 0) but no tag appears in `ghcr.io/projectbluefin/testsuite/desktop-screenshot`. Dashboard shows 0 screenshots.

**Cause:** When consumer repos (bluefin, bluefin-lts, dakota) call `e2e.yml` via `workflow_call`, `github.token` is scoped to the **caller's** repository. It can write to that repo's own GHCR packages, but NOT to `ghcr.io/projectbluefin/testsuite/desktop-screenshot` (owned by this repo). The push step has `continue-on-error: true`, so the failure is silent.

**Fix:** Grant explicit write access to each consumer repo on the `desktop-screenshot` package:
1. Go to [ghcr.io/projectbluefin/testsuite/desktop-screenshot](https://github.com/orgs/projectbluefin/packages/container/testsuite%2Fdesktop-screenshot/settings)
2. Package Settings → Manage Access
3. Add each consumer repo (`bluefin`, `bluefin-lts`, `dakota`) with `Write` role

This is a one-time UI operation — there is no programmatic API for cross-repo package grants.

---
## continue-on-error is forbidden on reusable-workflow jobs

**Symptom:** Every push to main produces "This run likely failed because of a workflow file issue." No jobs start. GitHub doesn't show a syntax error line number.

**Cause:** GitHub Actions forbids `continue-on-error` on a job that uses `uses:` to call a reusable workflow. The workflow is rejected at parse time — not at runtime — so every run fails before any job is created.

**Broken pattern:**
```yaml
jobs:
  e2e:
    continue-on-error: ${{ matrix.allow_failure == true }}  # FORBIDDEN with uses:
    uses: ./.github/workflows/run-testsuite.yml
    with:
      image: ${{ matrix.image }}
```

**Fix:** Remove `continue-on-error` entirely. If non-blocking matrix entries are needed, split blocking and non-blocking jobs into separate job definitions, each with its own `uses:` and `if:` condition — or just make all entries blocking.

**Verified with:** `actionlint` catches this (`continue-on-error is not available` for reusable workflow jobs). Run `actionlint` on any workflow that uses `uses:` before pushing.

---

## Workflow-level deny-all default in `e2e.yml`

`e2e.yml` declares `permissions: {}` at workflow level, immediately before `jobs:`. Any job that does not declare its own `permissions:` block therefore gets no token scope at all.

Job inventory and why the default is safe:

| Job | Own `permissions:` | Needs a token |
|---|---|---|
| `matrix` | none — inherits deny-all | no; it only runs `python3 -c` over `inputs.suites` and writes `$GITHUB_OUTPUT` |
| `compose` | `contents: read` + `packages: write` | yes — `podman login ghcr.io` with `secrets.GITHUB_TOKEN` |
| `e2e` | `contents: read` + `packages: write` | yes — same |

In a `workflow_call` workflow the workflow-level key sets the default for jobs without their own block and can only downscope; job-level blocks still apply, bounded by the caller's grant. Adding a job that needs a token therefore means adding its own `permissions:` block — it will not silently inherit one.

**When adding a job to `e2e.yml`:** give it an explicit `permissions:` block if it touches the API, GHCR, or the checkout token. A job that only computes outputs needs nothing.

---
