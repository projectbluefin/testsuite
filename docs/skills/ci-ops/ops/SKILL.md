---
name: ops
version: "1.0"
last_updated: "2026-07-29"
id: ops
one_line_purpose: Diagnose lab and CI failure signatures for testsuite runs.
entry_point: docs/skills/ci-ops/ops/SKILL.md
category: ci-ops
mcp_compliance_level: partial
status: active
dependencies: []
tags: [ops, lab, debugging, gdm, argo]
description: "Operational gotchas and failure signatures for the testsuite lab/CI setup. Load when debugging e2e failures, GDM, oomd, Argo, or runner issues."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Operational Gotchas

    # → success
    # /etc/gdm/custom.conf
    # WRONG — tests the container's DNS, not the VM's
    # CORRECT — tests DNS inside the VM
    # must return nothing
    # Listener running?
    # Jobs being picked up? (empty arc-runners is healthy — minRunners=0)
    # Runner logs (catch before pod completes)
    # WRONG — creates scratch/smoke.png/ directory, cp fails silently
    # CORRECT — pull to dir, then find the PNG inside
    # edit /tmp/ruleset.json, then PUT
    # .github/actions/my-action/action.yml

## When to Use

- Container-QA lanes fail in `wait_for_shell.py` with `bus-unavailable`
- VM boots to GDM greeter instead of a GNOME session
- Debugging infra-layer CI failures (runner container, D-Bus, AT-SPI)
- Adding new packages or patches to `container/Containerfile.runner`
- SSH assertion failures from unexpected output
- common-suite service health scenarios fail with unexpected `ActiveState` values
- Polkit rules presence check returns zero results
- A scheduled or push-only workflow is red and you need to find which merge broke it
- Session readiness fails with `ServiceUnknown` then `Could not connect: No such file or directory`

## When NOT to Use

- Writing behave step logic → `docs/skills/test-authoring/behave/SKILL.md`
- GNOME AT-SPI/dogtail patterns → `docs/skills/test-authoring/gnome/SKILL.md`
- bootc lifecycle steps → `docs/skills/test-authoring/bootc/SKILL.md`
- Workflow inputs, migration runs, manual.yml → `docs/skills/ci-ops/e2e-workflow/SKILL.md`

---

## Red Flags


- Using `_run(cmd)` in smoke suite for DNS or network checks (runs on container, not VM)
- Raising the `wait_for_shell.py` readiness timeout to fix `bus-unavailable` (the socket is absent indefinitely, not late — find why no session registers)
- Assuming a `bus-unavailable` readiness failure is a testsuite bug (the client re-resolves the bus every attempt; a permanently missing `/run/user/1000` is lab-side)
- Setting `sys.exit(1)` inside `before_scenario` (kills all subsequent scenarios silently)
- Lowering the SSH timeout below 60 seconds (hardware commands are slow in QEMU)
- Adding a second `-monitor` flag to QEMU (breaks `qemu_screendump.py`)
- Using `hasattr(context, 'failed_setup')` instead of `getattr(..., None)` (always True)
- Calling `sudo podman load` instead of rootless load (image goes to root storage)
- Using `oras pull` with a file path instead of a directory
- A workflow that builds or validates an artifact has no `pull_request` trigger and no equivalent job in `pr-validate.yml` (its first red run will be on `main`)
- Triaging a long-red scheduled workflow by blaming the most recent merge instead of locating the first failing run
- Treating `Could not connect: No such file or directory` from `gdbus --session` as terminal, or caching a session bus address across a GDM restart

## Verification


- [ ] Smoke suite network/DNS checks use `_run_host()` not `_run()`
- [ ] A `bus-unavailable` readiness failure was diagnosed from the `collect_session_diagnostics()` snapshot before any code change
- [ ] No `sys.exit()` calls in `before_scenario` / `after_scenario`
- [ ] `before_scenario` guard uses `getattr(context, 'failed_setup', None)`, not `hasattr()`
- [ ] SSH step timeout is 60s or higher for hardware/bootc commands
- [ ] `oras pull` targets a directory, not a file path
- [ ] Every workflow that builds a PR-breakable artifact is reachable from a `pull_request` trigger or a `pr-validate.yml` job
- [ ] Scheduled-workflow triage identified the first failing run and diffed it against the last green one
- [ ] Runner container changes followed by `build-runner.yml` dispatch before test runs
- [ ] Session-readiness helpers re-resolve `DBUS_SESSION_BUS_ADDRESS` on every attempt and require consecutive stable checks

## Relaunched applications need live AT-SPI nodes

`TestSandbox.after_scenario()` kills registered applications, but qecore's
`Application.instance` and test-owned node caches can still reference the old
process. A later scenario that launches the same application must enumerate
`tree.root.applications()` again and clear cached window nodes. A dead cached
node can emit a misleading `AT-SPI ... socket: No such file or directory`
warning even while the session bus and the newly launched application are
healthy.
Applications whose AT-SPI objects must survive the VM/container boundary must
be launched with `ATSPI_DISABLE_P2P=1`. The variable controls the application's
AT-SPI bridge, not the assistive client: setting it only on the runner container
does not stop libatspi from following the application's optional peer-to-peer
address under `at-spi2-*/socket`. Setting it on Firefox makes the application
export its objects over the shared accessibility bus instead of a process-local
socket that disappears when Firefox exits.
Firefox first-run UI can expose only a modal frame through AT-SPI, and both its
remote action and synthetic keyboard paths can block until the outer SSH
connection expires. The smoke contract therefore verifies the product-level
boundary: Firefox exposes a visible desktop window, produces no coredump, and
can be terminated cleanly. Browser-internal UI belongs in upstream Firefox tests.



## TuneD first-boot timeout in QEMU

On bootc images, `tuned.service` can invoke `bootc`/`rpm-ostree` while
first-boot storage initialization still owns the daemon. In the disposable
QEMU guest this can hold TuneD until systemd aborts it after the start timeout,
even though the desktop and all persistent image services are healthy. Keep
`tuned.service` in `IGNORED_FAILED_UNITS_IN_VM`; the ignore is conditional on
`systemd-detect-virt`, so the same failure outside virtualization remains a
release-blocking signal.

---

## On-demand references

Load these when you hit the specific topic:

- [Oneshot systemd service state — use Result, not ActiveState](references/oneshot-systemd-service-state-use-result-not-activestate.md)
- [Polkit rules path — check both directories](references/polkit-rules-path-check-both-directories.md)
- [Fedora version targets](references/fedora-version-targets.md)
- [GDM autologin required](references/gdm-autologin.md)
- [xdg-desktop-portal and graphical-session.target](references/xdg-desktop-portal-and-graphical-session-target.md)
- [SSH step timeout](references/ssh-step-timeout.md)
- [Smoke suite: _run() vs _run_host() for network checks](references/smoke-suite-run-vs-run-host-for-network-checks.md)
- [sys.exit(1) in before_scenario kills behave](references/sys-exit-1-in-before-scenario-kills-behave.md)
- [GNOME 50 requires qecore >= 4.12](references/gnome-50-requires-qecore-4-12.md)
- [OCI layer caching](references/oci-layer-caching.md)
- [@quarantine tag enforcement — two layers required](references/quarantine-tag-enforcement-two-layers-required.md)
- [--bootloader flag requires bootc >= 0.1.13](references/bootloader-flag-requires-bootc-0-1-13.md)
- [NVIDIA services always fail in QEMU](references/nvidia-services-always-fail-in-qemu.md)
- [systemd-oomd: both .service AND .socket fail in QEMU](references/systemd-oomd.md)
- [Bazzite extension state: use GetExtensionInfo, not Shell.Eval](references/bazzite-extension-state-use-getextensioninfo-not-shell-eval.md)
- [Rootless podman load fails in VM (exit 125)](references/rootless-podman-load-fails-in-vm-exit-125.md)
- [YAML orphan keys in e2e.yml](references/yaml-orphan-keys-in-e2e-yml.md)
- [Containerfile.runner requirements](references/containerfile-runner-requirements.md)
- [Python 3.14: sys.executable is empty in --pid=host containers](references/python-3-14-sys-executable-is-empty-in-pid-host-containers.md)
- [XDG_SESSION_TYPE and XDG_SESSION_DESKTOP must be forwarded](references/xdg-session-type-and-xdg-session-desktop-must-be-forwarded.md)
- [bootc install creates .0.origin alongside .0 — DEPLOY find must use -type d](references/bootc-install-creates-0-origin-alongside-0-deploy-find-must.md)
- [before_scenario and after_scenario setup guard pattern](references/before-scenario-and-after-scenario-setup-guard-pattern.md)
- [results.json captures first-pass only](references/results-json-captures-first-pass-only.md)
- [ublue-motd prepended to SSH output](references/ublue-motd-prepended-to-ssh-output.md)
- [Do not add a second -monitor flag to QEMU](references/do-not-add-a-second-monitor-flag-to-qemu.md)
- [common shell tools missing on bluefin:lts / bluefin-gdx](references/common-shell-tools-missing-on-bluefin-lts-bluefin-gdx.md)
- [ARC ghost runners — local dev routing](references/arc-ghost-runners-local-dev-routing.md)
- [oras pull: always use a directory, never a file path](references/oras-pull-always-use-a-directory-never-a-file-path.md)
- [GitHub API: rulesets require PUT not PATCH](references/github-api-rulesets-require-put-not-patch.md)
- [Cross-image tag skipping: @bluefin on non-bluefin images](references/cross-image-tag-skipping-bluefin-on-non-bluefin-images.md)
- [composefs file-capability regression](references/composefs-file-capability-regression.md)
- [Stdin Heredoc Consumption bug in run-gnome-tests.yaml](references/stdin-heredoc-consumption-bug-in-run-gnome-tests-yaml.md)
- [User Bootstrap primary group bug on fresh boots](references/user-bootstrap-primary-group-bug-on-fresh-boots.md)
- [git restore vs git checkout for full directory reset](references/git-restore-vs-git-checkout-for-full-directory-reset.md)
- [Composite actions vs checkout for cross-repo scripts](references/composite-actions-vs-checkout-for-cross-repo-scripts.md)
- [common suite execution model — runner container, not inside VM](references/common-suite-execution-model-runner-container-not-inside-vm.md)
- [smoke suite — pre-existing lab failures (GNOME 50 AT-SPI)](references/smoke-suite-pre-existing-lab-failures-gnome-50-at-spi.md)
- [lab ArgoCD template resolution timing](references/argo-mutex.md)
- [GNOME Shell readiness failures in container-QA lanes](references/gnome-shell-readiness-failures.md)
- [Workflows without a pull_request trigger break main silently](references/workflows-without-a-pull-request-trigger-break-main-silently.md)
- [qecore-headless restarts GDM — the session bus socket is replaced](references/qecore-headless-restarts-gdm-bus-socket-churn.md)
- [ghost-lab poller failure signatures — infra vs PR-caused](references/ghost-lab-poller-failures.md)
- [Coverage snapshot is generated — never hand-edit scenario counts](references/coverage-snapshot-generated.md)
