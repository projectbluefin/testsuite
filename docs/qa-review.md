# testsuite QA review

Coverage snapshot and known gaps live in `docs/skills/test-authoring/suite-map/SKILL.md`. Read that file for the current per-suite matrix and `@future` stub list rather than duplicating counts here.

The current branch's mechanical recount is 521 scenarios across 73 feature files:
411 active, 0 `@quarantine`, 110 `@future`/`@pending`/`@hardware_blocked` (see the generated snapshot in `docs/skills/test-authoring/suite-map/SKILL.md`). The five active
sudo-rs scenarios are included in the smoke total there.

## What this repo is responsible for

- Behave suite coverage and quality
- qecore + dogtail integration patterns
- Shared step/harness reuse across suites
- Reliable scenario-level validation logic

What it is **not** responsible for: lab hardware ops, ArgoCD, persistent titan VM lifecycle → `projectbluefin/lab`.

## uupd conditional suppression coverage

Issue #503 is blocked on a cross-repo contract. uupd checks battery state via
UPower (`OnBattery`, DisplayDevice `Percentage`, and the active power profile)
and metered networking via NetworkManager's `Metered` property. testsuite
cannot safely fake or restore those system-bus properties in the current VM
contract; writing `/sys/class/power_supply` or changing GNOME proxy settings
would test the wrong interfaces and could leak state between scenarios.

Keep the existing uupd binary/timer health check active. The proposed next step
is for the image or lab owner to provide an isolated simulation hook, after
which testsuite can add behavior coverage against `/etc/uupd/config.json` and
the upstream uupd check semantics.

## Highest-risk test correctness areas

1. GNOME Shell 50+ top-bar AT-SPI gaps (must use `Shell.Eval` fallback where needed)
2. dogtail API misuse (`requireResult` on `findChild`) causing runtime errors
3. Step-definition collisions in suites where multiple step files are loaded
4. Duplicated SSH logic instead of shared helper reuse

## Review gate for testsuite PRs

1. Are new scenarios added in the correct suite?
2. Are shared helpers reused where applicable?
3. Are step phrases unique within each loaded suite?
4. Is dogtail usage compatible with the current API behavior?
5. Do docs (`README.md`, `docs/runbook.md`, `docs/skills/`) still match behavior?
6. Are new scenario tests added as behave steps, with pytest reserved for `tests/unit/` helper coverage?
7. If scenario counts changed, are `docs/skills/test-authoring/suite-map/SKILL.md` and feature-file totals updated?

## Unit test coverage

Run unit tests with `python3 -m pytest tests/unit/ -q`. The `pytest` CI check (`unit-tests.yml`) runs on every PR and merge queue entry.

| File | What it covers |
|---|---|
| `test_gnome_shell_steps.py` | Shell.Eval, AT-SPI step helpers, ShellEval bool variants |
| `test_gnome_settings_steps.py` | Settings panel navigation and toggle helpers |
| `test_lifecycle_steps.py` | bootc upgrade/rollback/migration step helpers |
| `test_ssh_steps.py` | `run_ssh()`, journal/coredump matchers, output assertions |
| `test_timing.py` | SLA tag thresholds and timing helpers |
| `test_screenshot.py` | Screenshot capture helpers |
| `test_shared.py` | Shared step utilities |
| `test_screenshot_cli.py` | `screenshot_cli.main()` argument parsing and dispatch |
| `test_security_steps.py` | `_cosign_entries()` JSON validation and `_collect_values()` recursive extraction |
| `test_quarantine.py` | `@quarantine` / `@pending` / `@future` skip logic |
| `test_qemu_screendump.py` | `_ppm_to_png` conversion and `main()` entry point |
| `test_app_support.py` | `_desktop_path`, `_flatpak_available`, launch helpers |
| `test_system_health_steps.py` | `_has_image_reference`, `_running_in_vm`, ignored failed units |
| `test_brew_steps.py` | Brew step helpers and formula detection |
| `test_gnome_notifications_steps.py` | Notification step helpers |
| `test_retry.py` | Behave retry harness, `sys.executable` fallback |
| `test_parse_results.py` | `scripts/parse_results.py` parsing integration |
| `test_quarantine_age.py` | `scripts/check_quarantine_age.py` parsing and reporting |
| `test_orca_steps.py` | Orca screen-reader toggle steps, `_wait_for_orca` polling, restore semantics |
| `test_input_methods_steps.py` | `_run_in_vm` dispatch, exact `uint32` index parsing, success-latched input-source restore |
| `test_xwayland_steps.py` | `_xwayland_display_env` `pgrep` parsing, xprop/glxgears step branches |
| `test_install_kde_webdriver.py` | `scripts/install-kde-webdriver.sh` executed in a sandbox: pinned-SHA checkout ref, loopback-only unit bind posture, skip branches short-circuit |
| `test_validate_docs.py` | `scripts/validate_docs.py` frontmatter parsing, heading levels, and link/skill validation |
| `test_wait_for_shell.py` | `tests/shared/wait_for_shell.py` retry contract (Shell.Eval failures, missing panel, GDM-restart bus-socket churn, bus address re-resolution, stable checks, bounded deadline, autolaunch refusal, session diagnostics) |

## Current stub posture

- `flatcar/lifecycle`: 6 scenarios, 5 active — knuckle install, Ignition first-boot verification, update channel, automatic-update disable via `update.conf`, and afterburn implemented. Only the boot-order swap remains `@future`: booting the installed target disk requires KubeVirt boot-device ordering owned by `projectbluefin/lab`, and without it a reboot silently returns to the live disk. The suite is not yet reachable from `e2e.yml` (tracked in #704).
- `security/selinux`: all scenarios active (cosign verification across image variants).
- `nvidia`: still `@future` / `@hardware_blocked` until GPU passthrough exists in the lab.
- `kde-smoke`: 13 `@informational` scenarios in one feature file (repo totals: 491 scenarios / 64 feature files by mechanical recount; see the count-drift notice in `suite-map/SKILL.md`); Aurora-only Phase-2 harness proof. The shared KDE helpers and `e2e.yml` suite registration it depends on landed in #641-#645.
