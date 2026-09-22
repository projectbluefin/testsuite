---
name: troubleshooting
description: "Troubleshooting e2e workflow failures and flake signatures."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Troubleshooting

## Debugging failures

### podman load exits 125 (all GUI suites fail at "Load runner container into VM")

**Root cause:** `bluefin-test` lacks `/etc/subuid`/`/etc/subgid` entries. The Fedora 44 runner base image has a layer with `gid=12` (mail group) for `/var/spool/mail`. Rootless podman can't map this gid without subgid entries.

**Evidence:** Look for `lchown /var/spool/mail: invalid argument` in the "Load runner container into VM" step log.

**Fix:** The `e2e.yml` "Load runner container into VM" step now adds the entries and runs `podman system migrate` before loading. If you see this on an older branch, cherry-pick PR #224.

### behave crashes with PermissionError: [Errno 13] at ''

**Root cause:** Python 3.14 sets `sys.executable = ''` inside podman containers with `--pid=host`. Old `behave_retry.py` passed `sys.executable` directly to `subprocess.run`.

**Evidence:** Traceback in the "Run behave suite" step log ending at `subprocess.run(['', '-m', 'behave', ...])`.

**Fix:** `_find_python()` in `tests/shared/behave_retry.py` resolves a real interpreter via `shutil.which`. If you see this, the tests are being checked out from `main` (which lacks the fix) rather than the fix branch. Check `test_ref` in the run inputs.

### behave crashes with gi.RepositoryError: Typelib file for namespace 'xlib' not found

**Root cause:** `gobject-introspection` is not installed in the runner container. Fedora 44 + `--setopt=install_weak_deps=0` skips it even though `python3-gobject` depends on it weakly.

**Fix:** Rebuild the runner container after adding `gobject-introspection` to `container/Containerfile.runner`. Dispatch `build-runner.yml` to push a new `ghcr.io/projectbluefin/testsuite:runner`.

### qecore-headless exits with "pgrep: command not found"

**Root cause:** `procps-ng` is not in the runner container.

**Fix:** Same as above — add `procps-ng` to `Containerfile.runner` and rebuild.

### All AT-SPI calls silently fail / KeyError('XDG_SESSION_TYPE')

**Root cause:** `XDG_SESSION_TYPE` and `XDG_SESSION_DESKTOP` are not forwarded to the podman container. qecore-headless can't read them from `/proc/<pid>/environ` inside the container (permission denied), so it enters `__unavailable__` mode.

**Fix:** Add `-e XDG_SESSION_TYPE=wayland -e XDG_SESSION_DESKTOP=gnome` to the `podman run` call in `e2e.yml`, and write those same vars into `/tmp/session.env` before starting the container.

### Tests always run from main regardless of dispatched branch

**Root cause:** `github.ref_name` inside a `workflow_call` reusable workflow always resolves to the default branch (`main`). If `e2e.yml` uses it directly as the test checkout ref, it always pulls from `main`.

**Fix:** Pass `test_ref` through the `workflow_dispatch` caller (`manual.yml`, `migration-test.yml`, or another wrapper) using `github.ref_name` on the **workflow_dispatch** side (where it correctly reflects the dispatched branch), then forward it as an input to `e2e.yml`. Inside `e2e.yml`, the checkout must use `inputs.test_ref` directly — never `github.ref_name`. See ops.md "test_ref and github.ref_name" for the exact pattern.

### SSH never became ready

Check the serial log artifact. Common causes:
- ostree deployment missing: `bootc install` exited before writing layers (check for `ERROR: ostree deployment missing` in the install step)
- Kernel args wrong: `root=UUID=…` mismatch — verify `ROOT_UUID` in the install step output
- `selinux=0` is set, so SELinux policy isn't the cause

### GNOME session did not start

Check the serial log for GDM/systemd errors. Common causes:
- `gnome-ponytail-daemon` missing from the image
- GDM failing due to a missing display driver (virtio-gpu should always work)

The "Wait for GNOME session" step runs `journalctl -u gdm --no-pager -n 50` on timeout — look for that in the step output.

### behave: UndefinedStep

The testsuite is checked out sparse (`tests/<suite>` + `tests/shared` only). If the suite imports from a path outside those two directories, the copy will be incomplete. Verify the suite's `environment.py` imports.

### Timeout (120 min job limit)

The install + configure step is the heaviest (~10–15 min depending on image size). OCI layer caching should remove most repeat pull time; if jobs still hit the 120-minute limit, reduce suite scope or check for unusually large uncached images.
## dconf local.d overrides and test interference

**Pattern**: The E2E VM setup writes `allow-extension-installation=true` to
`/etc/dconf/db/local.d/00-ci-testing` so its `unsafe-mode@bluefin-test`
extension can be enabled after the GNOME session starts. The dconf profile
shipped by bluefin images is:
```
user-db:user
system-db:local
system-db:site
system-db:distro
```

`local` has higher priority than `distro`. Never write
`org.gnome.shell enabled-extensions` into `local.d/00-ci-testing`: it would
replace the image's default extensions, leaving Bluefin extension tests in
`INITIALIZED` or uninstalled states. Enable `unsafe-mode@bluefin-test` with
`gnome-extensions enable` after the session starts so it is added in the user
database without replacing the image default.

**Fix for tests checking distribution defaults**: Use `Gio.Settings.get_default_value()` which reads the compiled gschema default, bypassing ALL dconf databases:
```gherkin
* Run SSH command: "python3 -c \"import gi; gi.require_version('Gio','2.0'); from gi.repository import Gio; v = Gio.Settings.new('org.gnome.shell').get_default_value('enabled-extensions'); print(v.unpack() if v else [])\""
* Last command output contains "custom-command-list@storageb.github.com"
```

**When to use `gsettings get` vs `get_default_value`**:
- `gsettings get`: tests the EFFECTIVE value (what a real user sees). Affected by `local.d` CI overrides.
- `get_default_value`: tests whether the DISTRIBUTION ships a default. Immune to CI overrides.
- Use `gsettings get` for tests of locked keys (in `distro.d/locks/`) — locked keys aren't overridable by `local.d`.

**Key written by local.d/00-ci-testing**:
- `org.gnome.shell allow-extension-installation` = `true`

---
## Dashboard Static-Site Compilation and Path Robustness

**Pattern**: Python helper scripts (such as `compile_data.py`) executed from repository root inside GitHub Actions, but developed locally inside subdirectories, must resolve their base directories dynamically relative to `Path(__file__)` rather than hardcoding relative string paths like `./raw-runs`. This avoids directory execution discrepancies between local and CI environments.

**Pattern**: In Astro static sites, using `import.meta.glob('../data/runs/*.json', { eager: true })` to load detailed raw JSON files at build-time allows robust, offline-safe compilation of metrics, sparklines, and broken scenario aggregations directly from logs, entirely removing runtime client-side fetch or API performance overhead.

## `atspi_tree.txt` is missing from the artefacts

Artefact paths come from `tests/shared/results_dir.resolve_results_dir(context)`, which
resolves behave userdata `results_dir` first, then `TESTSUITE_RESULTS_DIR`, then the
`/tmp/results` default. `timing.py`, `screenshot.py`, `kde_faillog.py` and the AT-SPI tree
dump all route through it, so a run with an overridden results dir keeps its artefacts
together. A hardcoded `/tmp/results` literal writes outside that directory and the file
never reaches the uploaded artefact.

This fails silently: both `after_all` tree-dump sites sit inside `except Exception: pass`,
so a broken path or a missing import surfaces as "no `atspi_tree.txt`" and nothing else.
`tests/unit/test_suite_environment_contract.py` guards it by asserting no `after_all`
contains a `/tmp/results` literal. Resolve the directory once and reuse it for both the
existence check and the write.

## Scenario timing and SLA reporting contract

`tests/shared/timing.py` appends scenario run metrics to `timings.jsonl` in the results
directory. The `gnome-e2e` composite action reads back `results/timings.jsonl` to report SLA
violations in job summaries.

- SLAs are defined solely via scenario tags matching `@sla_<n>s` (e.g. `@sla_10s`).
- Scenarios without an `@sla_<n>s` tag do not have a default SLA (`sla_s: null`) and do not violate.
- Violations are reported and surfaced as warnings in CI summaries; they do not fail the scenario run directly.
- Strict gating is driven by the `results-timing` recipe in `Justfile` checking `TIMING_SLA_STRICT=1` (exiting 1 on violations), not by module-level constants in `timing.py`.
- `tests/unit/test_timing_contract.py` validates that all keys consumed by the action summariser and the `results-timing` recipe in `Justfile` are produced by `timing.py:record_end` and ensures unconsumed public configuration constants are not added to `timing.py`.

