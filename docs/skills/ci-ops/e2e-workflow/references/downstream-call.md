---
name: downstream-call
description: "How downstream repos call the reusable e2e workflow."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Downstream Call

## How to call it from another repo

**Pin to `@v1`** — testsuite auto-updates v1 to main after every merge. Renovate does not need to manage this SHA.

```yaml
# .github/workflows/run-testsuite.yml  (in the consumer repo)
jobs:
  e2e:
    uses: projectbluefin/testsuite/.github/workflows/e2e.yml@v1
    with:
      image: ghcr.io/projectbluefin/bluefin:testing
      suites: smoke,common,vanilla-gnome
```

Do **not** use a full SHA pin (creates Renovate churn) or `@main` (floating, security risk).

### Inputs

| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | string | `ghcr.io/projectbluefin/dakota:testing` | OCI image to test (must be a bootc/ostree image) |
| `target-image` | string | `""` | Full OCI ref to upgrade TO (optional). When set and the `lifecycle` suite is running, stages this image via `bootc switch` before the test suite. Used for migration testing. |
| `suites` | string | `smoke` | Comma-separated suite names: `smoke`, `developer`, `dx`, `software`, `vanilla-gnome`, `bazzite`, `common`. Note: `lifecycle` is also accepted but is not listed in the input description — use `manual.yml` or `projectbluefin/actions` wrapper workflows for lifecycle runs. |
| `skip_native_apps` | boolean | `false` | When `true`, skips `@native_app` scenarios (Flatpak apps that may not be installed in all variants) |
| `screenshot_flatpaks` | string | `""` | Comma-separated Flatpak app IDs to launch-and-screenshot after the test run. See [Flatpak screenshot gallery](../../../flatpak-screenshots/SKILL.md) for full details. |
| `chunked_enabled` | boolean | `false` | When `true`, sets `ZSTD_CHUNKED=true` so `@zstd_chunked` lifecycle scenarios run. Enable once the image ships `tar+zstd` OCI layers. |
| `test_ref` | string | `main` | `projectbluefin/testsuite` ref to check out for test content. Wrapper workflows that start from `workflow_dispatch` should resolve this on the caller side with `${{ github.event.inputs.test_ref || github.ref_name }}`. |

Multiple suites run as a matrix (parallel jobs):

```yaml
with:
  image: ghcr.io/projectbluefin/myimage:pr-123
  suites: smoke,developer
```

**Dynamic suite sharding**: `suites: smoke` expands to `smoke-a` + `smoke-b`, and `suites: common` expands to `common-a` + `common-b`. After checkout, the workflow glob-resolves `tests/<suite>/features/*.feature`, sorts alphabetically, and splits into two deterministic shards:

```python
files = sorted(glob.glob(f"tests/{suite}/features/*.feature"))
chunk_size = math.ceil(len(files) / 2)
chunk = files[shard_index * chunk_size:(shard_index + 1) * chunk_size]
```

Do **not** hardcode per-shard feature lists. New `.feature` files must land in a shard automatically or they will be silently skipped.

Smoke shards still use `tests/smoke/` (same directory, same `environment.py`, same steps) and normalize screenshot publishing to `:smoke-latest` (last writer wins). Common shards use `tests/common/` and pass their feature-file paths directly to the runner-side behave invocation.

### Unit-test parallelism

`unit-tests.yml` runs pytest with `-n auto`, but coverage must stay on `coverage.py`, not a bare `pytest-cov` invocation. In this repo, xdist plus `pytest-cov` under-reports coverage. Keep this pattern:

```bash
COVERAGE_PROCESS_START=.coveragerc coverage run -m pytest -n auto tests/unit/ -v
coverage combine
coverage xml
coverage report --fail-under=75
```

`.coveragerc` must keep `parallel = True` and `patch = subprocess` so worker coverage files are written and merged correctly.

### Lifecycle suite — special execution model

The `lifecycle` and `common` suites do **not** run inside the VM container. They run from the GHA runner via SSH — `lifecycle` because the test process must survive the mid-upgrade reboot; `common` because it only needs dconf/shell access, not a full AT-SPI bus. The pipeline branches at the "Run behave suite" step:

```
if [[ "${SUITE_DIR}" == "common" || "${SUITE_DIR}" == "lifecycle" ]]
  → python3 tests/shared/behave_retry.py ...   (runner-side, SSH via VM_IP/VM_USER env vars)
else
  → scp tests/ to VM, then
    podman run --rm ghcr.io/projectbluefin/testsuite:runner \
      "python3 /tmp/bluefin-tests/tests/shared/behave_retry.py ..."  (inside VM)
```

When `target-image` is set and the `lifecycle` suite is running, the **"Pre-stage target image via bootc switch"** step SSHes into the VM and runs `sudo bootc switch '<target-image>'` before the behave run begins, staging the upgrade target.

After the lifecycle suite finishes, a separate **"Capture post-upgrade desktop screenshot"** step re-SSHes with `ControlMaster=no` (fresh connection after reboot), waits up to 60 s for the Wayland socket at `/run/user/1001/wayland-0`, and calls `org.gnome.Shell.Eval` via gdbus to capture a screenshot. The screenshot is saved to `results/screenshot_lifecycle_upgrade_final.png` and uploaded in the `e2e-results-*` artifact.

A **"Capture post-migration screenshot and status"** step also runs (`always()`, `continue-on-error: true`) for the lifecycle suite. It captures the QEMU framebuffer via `tests/shared/qemu_screendump.py` and SSHes in to write `results/migration-status.txt` containing `bootc status`, `fastfetch`, and `os-release` output — useful for confirming the active image ref and OS version after a migration reboot. Both files are included in the `e2e-results-*` artifact.

**Preferred manual trigger:** dispatch `upgrade-test.yml` in `projectbluefin/actions` — it calls `e2e.yml` cross-repo (which works). Do NOT dispatch `manual.yml` in this repo for lifecycle runs (see ops.md "manual.yml startup_failure").
## test_ref and github.ref_name

**Symptom:** Tests always run from `main` even when dispatching `manual.yml` from a feature branch.

**Cause:** `github.ref_name` inside a `workflow_call` reusable workflow always resolves to the **default branch** (`main`), not the caller's branch. This is a GitHub Actions platform behavior — it does not reflect the dispatched branch.

**Fix:** Set `test_ref` in the `workflow_dispatch` caller (`manual.yml`, `migration-test.yml`), where `github.ref_name` correctly reflects the dispatched branch:

```yaml
jobs:
  test:
    uses: ./.github/workflows/e2e.yml
    with:
      test_ref: ${{ github.event.inputs.test_ref || github.ref_name }}
```

Never use `github.ref_name` as a test-checkout ref inside `e2e.yml` itself — always `inputs.test_ref`.

---
## manual.yml: do not add @ref to same-repo workflow calls

**Symptom:** `manual.yml` workflow_dispatch runs fail immediately with `startup_failure`.

**Cause:** GitHub Actions returns `startup_failure` when a `workflow_dispatch` workflow calls a same-repo reusable workflow with an explicit ref (`uses: ./.github/workflows/e2e.yml@main`).

**Fix:** Use the bare local path with no ref:
```yaml
uses: ./.github/workflows/e2e.yml    # correct
# NOT:
# uses: ./.github/workflows/e2e.yml@main   # causes startup_failure
```

Cross-repo calls (`projectbluefin/testsuite/.github/workflows/e2e.yml@<sha>`) work correctly.

For lifecycle manual runs, dispatch `upgrade-test.yml` in `projectbluefin/actions` — it calls `e2e.yml` cross-repo with full lifecycle inputs.

---
