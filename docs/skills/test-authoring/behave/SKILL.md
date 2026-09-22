---
name: behave
version: "1.0"
last_updated: "2026-07-29"
id: behave
one_line_purpose: Write behave scenarios and step definitions for testsuite suites.
entry_point: docs/skills/test-authoring/behave/SKILL.md
category: test-authoring
mcp_compliance_level: partial
status: active
dependencies: []
tags: [behave, bdd, steps]
description: "How to write behave scenarios and step definitions for the testsuite repo. Load when editing .feature files or steps.py."
metadata:
  type: pattern
  audience: agents
  maturity: stable
---
# Behave Patterns Reference


## When to Use


- Writing or extending behave `.feature` files in any suite
- Reusing or checking shared SSH step phrases
- Debugging `UndefinedStep`, `AmbiguousStep`, or dry-run failures
- Verifying suite-local step placement and cross-suite visibility

## When NOT to Use


- Smoke-suite GUI implementation details that belong in `docs/skills/test-authoring/gnome/SKILL.md`
- Bootc / upgrade / rollback workflow rules that belong in `docs/skills/test-authoring/bootc/SKILL.md`
- CI workflow ownership, runner, or reusable-action changes that belong in workflow skills

## Core Process


1. Read the target `.feature` file and the suite's `steps/*.py` before adding phrases.
2. Reuse `tests/shared/ssh_steps.py` for generic SSH command/assertion steps instead of duplicating helpers.
3. Star-importing `tests/shared/ssh_steps` obligates the suite to set the context attributes those steps read. `run_ssh()` builds its argv via `ssh_config.ssh_argv(context)`, which prefers `context.ssh_key`, `context.ssh_user`, `context.vm_ip`, `context.ssh_port` and then falls back to userdata/env/defaults; a suite that skips this no longer fails loudly — it silently runs against default credentials. Call `tests.shared.ssh_config.populate_ssh_context(context)` from the suite's `before_all` (see `tests/software/features/environment.py`) — it resolves context attributes → behave userdata → `SSH_KEY`/`VM_IP`/`VM_USER`/`SSH_PORT`/`TMT_SSH_PORT` env vars → runner defaults, which is the same source suite-local SSH helpers (e.g. the software suite's `_flatpak()`) must use. Never let a suite keep a second, env-only SSH path alongside the shared steps.
4. Keep step phrases unique within the loaded suite and check for collisions before committing.
5. Choose assertions that match the command shape: equality for single-line output, substring for multiline output.
6. Run `behave --dry-run` on the touched suite before pushing so undefined or ambiguous phrases fail locally.

## `grep -q` vs `grep -c` for existence checks


**Never use `grep -c ... || echo 0`** for existence checks in SSH commands. This is a false-positive trap:
- On no match: `grep -c` prints `0` and exits 1, then `echo 0` fires and the overall command exits 0
- The output is now `"0\n0"` — the step `SSH command output is not "0"` sees `"0\n0"` which is not equal to `"0"` and **passes falsely**

**Correct pattern** — use `grep -q` and assert the return code:
```gherkin
Scenario: Portal interface is present
  * Run SSH command: "gdbus introspect ... | grep -q 'InterfaceName'"
  * SSH command return code is "0"
```

`grep -q` exits 0 on match, 1 on no match, with no output. The return code assertion is the signal.
The same applies to `wc -l`, `grep -c`, or any count-based check used as an existence gate.

## Quote embedded Python in SSH commands safely

`Run SSH command` already wraps the remote command in a quoted Gherkin string
and sends it through a remote Bash shell. Put the Python expression in Bash
ANSI-C single quotes (`$'...'`) and use double quotes inside the Python code
so shell word-splitting cannot break expressions containing parentheses or
dictionary literals.

```gherkin
* Run SSH command: "bootc status --json | python3 -c $'import sys,json; d=json.load(sys.stdin); print(d.get(\"status\",{}))'"
```

The `$'...'` ANSI-C quote is intentional: the shared SSH step wraps commands
with `bash -c`, which consumes the escaped quotes before Python receives them.
Audit every `python3 -c` added to an SSH command for this pattern. Avoid
nested escaped double quotes around the entire Python expression; those
escapes can survive into the remote shell and expose Python punctuation to
shell parsing.

## Assert parsed values, not substrings

`gsettings get` returns GVariant text such as `uint32 1`. `assert "1" in output`
also matches `uint32 10`, `uint32 11`, and `uint32 100`, so a failed state change
reads as a pass. Parse the payload and compare it exactly:

```python
_UINT32_RE = re.compile(r"^(?:uint32\s+)?(\d+)$")

def _parse_index(output: str) -> int | None:
    match = _UINT32_RE.match(output.strip())
    return int(match.group(1)) if match else None

assert _parse_index(output) == 1, f"Current input source is not 1: {output}"
```

An unparseable value must fail, never pass by default.

## Restore hooks must only latch on success

A cleanup helper that saves state and restores it later is normally guarded by a
`_restored` flag so the explicit step and the `context.add_cleanup` hook do not
run twice. Set that flag **only after every restore command actually returned 0**:

```python
failures = []
for key in ("sources", "current"):
    output, rc = _run_in_vm_checked(f"gsettings set {schema} {key} {shlex.quote(value)}")
    if rc != 0:
        failures.append(f"{key} (rc={rc}): {output}")
if failures:
    raise AssertionError("Failed to restore ...: " + "; ".join(failures))
state["_restored"] = True
```

Latching the flag on a *failed* command turns the cleanup hook into a no-op: the
retry never happens and the mutated state leaks into every later scenario in the
run. Surface the failure instead of swallowing it.

## Common suite `ujust` recipe coverage

Dakota's interactive recipes shadow `fzf`/`gum`/`gh` on `PATH`; mocks must answer each
prompt distinctly and assert on the invocation, not merely that the tool ran
([reference](references/mocking-interactive-cli.md)).

Keep SSH-based `ujust` recipe checks in `tests/common/features/common_ujust.feature`.
Prefer assertions against the wrapper's own output, not the underlying tool's raw
output — for example `ujust bios-info` prints `Manufacturer:` / `Release Date:`
labels itself, so checking for raw `dmidecode` keys like `Vendor` is brittle.

If a recipe is gated by `gum choose`, `pkexec`, or package-install side effects,
prefer a non-interactive entry point in the recipe itself. Where the image has
not shipped one yet, land the coverage behind a `@requires_*` skip tag so it
activates when the contract lands, instead of leaving the scenario `@pending`
forever. `ujust toggle-updates` flips `uupd.timer` or
`rpm-ostreed-automatic.timer` (not `ublue-update.timer`) and is covered via its
non-interactive `ACTION=enable|disable|cancel` argument (see the reference
below).

Two recipes are worked out in detail in
[`references/ujust-noninteractive.md`](references/ujust-noninteractive.md):
`toggle-updates` gained a non-interactive `ACTION` entry point in
`projectbluefin/common` and is covered by a `@requires_toggle_action` scenario
(`projectbluefin/testsuite#499`), while `toggle-devmode` still has none and is
deliberately uncovered (`projectbluefin/testsuite#500`).

### uupd conditional suppression coverage

Do not simulate uupd's battery or metered-network suppression in testsuite
scenarios. uupd reads `org.freedesktop.UPower` and
`org.freedesktop.NetworkManager` system-bus properties, and the current image
and lab contracts do not provide a safe, isolated way to override those
properties and restore the host state. The `/sys/class/power_supply` files
and GNOME proxy settings are not the interfaces uupd checks.

Until the image or lab supplies a supported simulation hook, keep the existing
uupd presence/timer health check and document this as a coverage gap. A future
implementation must use the upstream uupd config path (`/etc/uupd/config.json`)
and keys documented by ublue-os/uupd, and must define how the UPower and
NetworkManager state is injected without changing the host's persistent state.

## MIME type handler verification (smoke suite)


Use `xdg-mime query default <mime-type>` to verify handler registration without launching apps. Assert against known `.desktop` file names or an allow-set:

```python
DOCUMENT_VIEWERS = {"org.gnome.Papers.desktop", "evince.desktop"}
actual = subprocess.run(["xdg-mime", "query", "default", "application/pdf"],
                        capture_output=True, text=True).stdout.strip()
assert actual in DOCUMENT_VIEWERS
```

This validates the MIME database end-to-end (xdg-mime, .desktop file registration, mimeapps.list) without window management flake.

For lightweight smoke-suite CLI assertions (for example `gsettings`, `pgrep`, or `journalctl` checks), prefer qecore's built-in command capture steps in the `.feature` file instead of adding wrappers:

For MIME-handler coverage, prefer direct `subprocess.run(["xdg-mime", "query", "default", mime])` helpers in `tests/smoke/features/steps/steps.py` and assert the resolved `.desktop` file (or an allowed viewer set) instead of launching the app with `xdg-open`. This keeps smoke checks local to the VM and avoids window-management flake while still validating Bluefin's handler registration end to end.

```gherkin
* Run and save command output: "gsettings get org.gnome.desktop.a11y.keyboard enable"
* Return code of last command output "is" "0"
* Last command output "contains" "true"
```

Do **not** invent alternate phrases like `Run command:` / `Command output contains ...` in smoke features unless you are also intentionally adding matching step definitions.

When a smoke assertion needs an allow-set result (for example `systemctl is-enabled`
returning either `enabled` or `static`), keep using the built-in qecore command
steps and encode the allow-set in the shell command itself:

```gherkin
* Run and save command output: "systemctl is-enabled uupd.timer | grep -E '^(enabled|static)$'"
* Return code of last command output "is" "0"
```

This avoids adding a one-off step definition just to express "one of these two
values is acceptable".

For smoke steps that must run several host commands, reuse the suite's canonical
`_run_host` helper with `from steps.steps import _run_host`. It handles local
qecore-headless execution and the runner-container SSH fallback. Do not duplicate
SSH argument construction or container detection in a new smoke step module.

## Flatpak per-app permissions: assert via CLI, not Flatseal's GUI

Flatseal (`com.github.tchx84.Flatseal`) is only a front end over `flatpak override`
and the portal permission store. Cover per-app permission behaviour with the CLI —
it needs no desktop session and no AT-SPI:

| What Flatseal shows | CLI assertion surface |
|---|---|
| Per-app toggles the user has changed | `flatpak override --user --show <app>` |
| Effective manifest permissions | `flatpak info --show-permissions <app>` |
| Portal grants (documents, notifications, background) | `flatpak permissions [<table>]` |

Two properties make these scenarios survivable in CI, where
`flatpak-preinstall.service` is masked and `/var/lib/flatpak` is not seeded
(the reason `tests/smoke/features/flatpak_permissions.feature` is quarantined):

1. **`flatpak override --user` accepts an application ID that is not installed.**
   Use a synthetic ID such as `org.projectbluefin.TestsuitePermissionProbe` so the
   round-trip neither depends on nor clobbers real installed apps. Always finish the
   scenario with `Reset flatpak user overrides for ...`.
2. **A sweep that passes on an empty install set is not coverage.** That is why
   `Every installed flatpak app exposes a parsable permission set` is `@pending` on
   #706. More traps: [references/flatpak-permissions.md](references/flatpak-permissions.md).

`flatpak override --show` emits a keyfile, not flag syntax:

```ini
[Context]
sockets=!wayland;
```

Parse it (`parse_flatpak_context` in
`tests/software/features/steps/flatpak_permissions_steps.py`): split on the first
`=` and compare the key — matching bare key names against `filesystems=home;`
never matches and passes falsely.

## Software suite SSH context

`tests/software/features/environment.py` calls `populate_ssh_context(context)` in
`before_all` (#718), so the shared `tests/shared/ssh_steps.py` steps work there.

## `@flatpak_cli` marks image-agnostic software scenarios

`tests/software/features/environment.py` skips any `@software` scenario when Bazaar
(`io.github.kolunmi.Bazaar`) is absent — unless the scenario also carries
`@flatpak_cli`. Tag CLI-only, image-agnostic software scenarios with `@flatpak_cli`
so they still run on gnomeos and other non-Bluefin images.

## `@requires_cached_image` gates scenarios on a pre-pulled OCI image

A scenario must never pull the container image it needs — a cold
`distrobox create` pulls inside the scenario and eats the CI timeout (#501).
Tag it `@requires_cached_image`; `skip_when_image_not_cached()` in
`tests/shared/image_cache.py`, called from the suite's `before_scenario` right
after `skip_quarantine`, reads the image refs out of the scenario's own step
text, probes each with `podman image exists` on the DUT, and skips while any is
absent. The scenario then activates on its own once the image is cached.

It is a **runtime capability gate** like `@requires_brew`, not a non-runnable
tag: keep it out of `_SKIP_TAGS` / `NON_RUNNABLE_TAGS` / `BEHAVE_TAG_ARGS`, and
never pair it with `@pending` or `@future` — `skip_quarantine` returns first and
the gate goes inert. See
[the cached-image gate reference](references/cached-image-gate.md).

## Feature scaffolding with @future


Use `@future` when the step implementation isn't ready yet:

```gherkin
@future
Scenario: Hardware watchdog is active
    Given the VM has TPM 2.0
    ...
```

Remove `@future` when all three are true:
1. VM spec supports the hardware/feature
2. Step implementations are complete

Find remaining stubs:
```bash
just list-stubs
# or
grep -r "@future" tests/*/features/*.feature
```

## Selective reruns with @retry


Use a plain `@retry` tag on scenarios whose common failure mode is
infrastructure timing (GNOME session startup, AT-SPI render races, slow app
launch in QEMU). `tests/shared/behave_retry.py` only re-runs failing rerun
entries whose effective tags include `retry`; untagged failures fail the job
immediately after the first pass.

The retry budget comes from `BEHAVE_RETRIES` / `--retries` (default: `2`), so
`@retry` means "eligible for the normal retry loop" rather than a per-scenario
count override.

## Suite layout


```
tests/
  smoke/          # GUI smoke — behave + dogtail
  developer/      # developer tools
  software/       # software installation
  flatcar/        # Flatcar compatibility
  lifecycle/      # bootc upgrade/rollback
  security/       # security posture
  dx/             # DX variant
  nvidia/         # GPU tests
  hardware/       # hardware feature detection
  vanilla-gnome/  # upstream GNOME parity
  shared/
    ssh_steps.py  # canonical SSH step library
```

Each suite has:
```
<suite>/
  features/
    *.feature
    environment.py
    steps/
      steps.py   (+ additional step files)
```

## Cross-suite step isolation


Each suite loads only its own `steps/*.py` files plus `qecore.common_steps`. A step defined in `tests/software/features/steps/steps.py` is **not** available in `tests/developer/features/steps/steps.py` even if both import qecore.

**Rule:** When the audit agent (or any agent) moves a step phrase from a shared/smoke context into a suite-specific file, verify that every `.feature` file using that phrase is in the same suite. If multiple suites use the phrase, define it in each suite's `steps.py`.

Lesson surfaced 2026-05-30: `No journal entries match "{pattern}"` was added to `software/steps.py` but `ptyxis.feature` (developer suite) also used it — causing `UndefinedStep` at runtime.

Isolation cuts the other way too: an `environment.py` hook that imports a module containing `@step` decorators registers those phrases into the suite it runs in. `tests/shared/ssh_steps.py` collides with the DX suite's own `SSH command return code is "{code}"`, so hooks that need to run a command on the DUT resolve connection details from `tests/shared/ssh_config.py` and call `subprocess` directly rather than importing the step library (#501).

## behave rerun output can contain non-path noise


`behave --format rerun` on 1.3.x adds header comments like:

```text
# -- RERUN: 7 failing scenarios during last test run.
tests/smoke/features/foo.feature:5
```

`tests/shared/behave_retry.py` must filter out comment or non-`.feature[:line]`
entries before retrying. Passing those lines back to behave causes:

```text
ConfigError: No steps directory in '/.../# -- RERUN: 7 failing scenarios ...'
```

## `Last command output stripped "is"` vs multiline output


`stripped "is" "<value>"` strips whitespace from the **entire** captured output and checks equality. This only works correctly for **single-line** command output (e.g. `grep -c`, `echo X`).

For commands that produce multiline output (e.g. `flatpak install ... 2>&1; echo rc:$?`), use `Last command output contains "rc:0"` instead.

```gherkin
# WRONG — fails when flatpak install produces install progress lines
* Last command output stripped "is" "rc:0"

# CORRECT — substring check works with multiline output
* Last command output contains "rc:0"
```

## Bluefin desktop identity defaults: `gsettings get` vs `dconf read`


In the SSH-driven `common` suite, validate Bluefin desktop identity overrides with the API that matches the schema type:

- Use `gsettings get` for regular schemas shipped via `zz0-bluefin-modifications.gschema.override` (for example `org.gnome.desktop.interface accent-color` or `org.gnome.desktop.app-folders folder-children`).
- Use `dconf read` for relocatable schemas and extensions without XML schemas (for example custom media-key keybindings under `/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/`, Search Light under `/org/gnome/shell/extensions/search-light/`, and Ptyxis profile palette keys under `/org/gnome/Ptyxis/Profiles/<uuid>/`).

This keeps common-suite assertions aligned with how Bluefin actually ships those defaults in `projectbluefin/common`.

## Quarantine Protocol


When a scenario fails in QEMU CI due to a known environment limitation (not a code bug), tag it `@quarantine` and file a tracking issue:

```gherkin
@quarantine
Scenario: Flathub remote is configured
  ...
```

The CI runs behave with `--tags ~quarantine`, so quarantined scenarios are skipped and do not block the gate.

### When to quarantine vs fix

| Situation | Action |
|---|---|
| Scenario fails because a first-boot service is masked in CI | Quarantine + image-side issue |
| Scenario fails due to GNOME 50 API change | Quarantine + investigate new API |
| Scenario fails due to a real regression in the image | Do NOT quarantine — it's a gate hit |
| Scenario fails intermittently (flaky network, timing) | Add `@retry` tag instead |

### Known quarantine categories (2026-06)

**smoke-b:** screen lock (#528), PDF/PNG/video MIME defaults (#529)
- Screen lock: GNOME 50 headless QEMU — lock screen doesn't engage within 10s
- MIME defaults: Fedora system mimeapps.list sets Firefox as default; Flatpak Papers/Loupe don't override at system level on fresh install

**common-a/b:** 13 scenarios in dconf, flatpak, immutable, polkit (#531)
- Flatpak: /var/lib/flatpak not preserved from OCI build; flatpak-preinstall.service masked in CI
- dconf: some schema defaults may require un-investigated setup; Ptyxis palette is user-session state
- Immutable: rpm-ostree status / bootc status / /usr ro failing for unknown reason in fresh QEMU bootc install
- Polkit: rules may be in /usr/share/ not /etc/polkit-1/rules.d/

## Behave Background scope — don't put app-open preconditions for all scenarios


Behave's `Background:` runs before **every scenario** in the feature, including scenarios that don't
need the app to be open (e.g. coredump checks, version assertions, cleanup verifications).

**Anti-pattern:**
```gherkin
Feature: GNOME Settings smoke tests
  Background:
    * Settings window is accessible   # ← runs before EVERY scenario

  Scenario: Settings closes cleanly via Ctrl+Q
    * Key combo: "<Ctrl><Q>" with uinput
    * Settings is no longer running   # ← explicitly kills Settings

  Scenario: No gnome-control-center coredump after session start
    * No coredump entries exist for "gnome-control-center"
    # ^ Background runs first: tries to find Settings after it was just killed → FAILS
```

**Fix options (prefer first):**
1. Move regression/coredump checks to a separate feature file without an app-open Background
2. If the Background must re-launch the app, split launch from accessibility check:
   ```gherkin
   Background:
     * Launch Settings via command
     * Settings window is accessible
   ```
   Then even after Ctrl+Q, the next Background re-launches it.

**Rule:** A feature Background should only assert state that is valid for ALL scenarios in that
feature. If any scenario tears down that state, either restructure the teardown or move the
non-dependent scenarios to a separate feature.


| Rationalization | Reality |
|---|---|
| "I'll just add a tiny local SSH helper." | Shared SSH phrases already exist in `tests/shared/ssh_steps.py`; duplication creates drift and inconsistent assertions. |
| "This phrase is descriptive enough; collisions are unlikely." | Behave loads all step files in a suite together, and duplicate phrases fail at runtime with `AmbiguousStep`. |
| "Equality is stricter, so I'll use it for all command output." | `... stripped "is"` only works for single-line output; multiline commands need substring assertions. |
| "A dry-run is overkill for a simple feature edit." | CI runs dry-run and will catch missing step definitions immediately; local dry-run is the cheap failure path. |

## Red Flags


- New suite-specific code duplicates `Run SSH command` or other shared SSH assertions
- A `.feature` file introduces a phrase with no matching `@step` decorator
- The same decorator text appears in multiple step files loaded by one suite
- A test checks relocatable dconf keys with the wrong tool (`gsettings` vs `dconf read`)
- A PR changes `tests/**` without a matching skill update
- A feature Background opens an app but a scenario in the same feature closes that app (next scenario's Background will fail)
- `@retry` added to a scenario to mask a missing retry loop in the underlying `_<app>_app()` helper

## Verification


- [ ] New or changed step phrases exist in the correct suite or shared helper module
- [ ] No duplicate step phrases exist in the touched suite
- [ ] `behave --dry-run` passes for the touched suite
- [ ] Output assertions match the command shape (single-line equality vs multiline substring)
- [ ] Any newly discovered reusable pattern is written back to a skill file in the same PR

## On-demand references

- [Shared SSH helpers and where to use them.](references/shared-ssh.md)
- [When to use local subprocess instead of SSH in the smoke suite.](references/smoke-vs-ssh.md)
- [Avoiding duplicate step phrases and AmbiguousStep errors.](references/ambiguous-steps.md)
- [Mocking interactive CLI tools (gum, fzf, gh) in ujust coverage.](references/mocking-interactive-cli.md)
- [Which ujust recipes can be driven non-interactively, and why the rest stay @pending.](references/ujust-noninteractive.md)
- [Gating scenarios on a pre-pulled OCI image with @requires_cached_image.](references/cached-image-gate.md)

## Sources

- Behave documentation: `/behave/behave`
