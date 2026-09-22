---
name: shared-ssh
description: "Shared SSH helpers and where to use them."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Shared Ssh

## Shared SSH helpers

`tests/shared/ssh_steps.py` is canonical for:
- `Bluefin VM is booted and reachable over SSH`
- `Run SSH command: "<cmd>"`
- `SSH command return code is "<code>"`
- `SSH command output "is" "<expected>"`
- `SSH command output stripped "is" "<expected>"`
- `SSH command output contains "<text>"`
- `SSH command output does not contain "<text>"`
- `SSH command output is not "<value>"`
- `SSH command output is not "<a>" and not "<b>"`
- `SSH command output is not empty`

For Bluefin desktop-model assertions, keep SSH-only Flatpak checks in the
`common` suite (remote configuration, bundled app IDs, `/usr/share/applications`
scans). GUI Flatpak-management coverage (Bazaar, Flatseal, per-app permissions)
belongs in the `software` suite.

When asserting Bluefin's bundled terminal app over SSH, accept either
`org.gnome.Ptyxis` or `com.raggesilver.BlackBox`. Images may ship either app ID
depending on the terminal packaging generation under test.

Import in suite `environment.py`:
```python
from tests.shared.ssh_steps import *  # noqa: F401,F403
```

## Importing the steps is only half the contract

`run_ssh()` resolves its connection details through
`ssh_config.ssh_argv(context)`, which prefers **`context`** attributes
(`vm_ip`, `ssh_user`, `ssh_key`, `ssh_port`) and only then falls back to behave
userdata, environment variables and runner defaults. A suite that star-imports
`ssh_steps` without populating those attributes no longer raises
`AttributeError` — it silently connects with *default* credentials, which is
worse. Populate them in `before_all`.

To keep that failure mode diagnosable, `ssh_argv()` prints the resolved
destination once per distinct target, together with where each field came from:

```
SSH target: bluefin-test@127.0.0.1:22 key=/home/bluefin-test/.ssh/id_ed25519 (ssh_key=default,ssh_port=default,ssh_user=default,vm_ip=default)
WARNING: no SSH connection details were configured — using built-in runner defaults. ...
```

The warning fires only when *every* field fell back to a built-in default,
i.e. nothing (context, userdata, or environment) configured the run. Use
`ssh_config.resolve_ssh_details_with_sources(context)` when a suite or test
needs to assert the details came from a non-default source.


Resolve them through the shared helper rather than hand-rolling per suite:

```python
from tests.shared.ssh_config import populate_ssh_context

def before_all(context):
    populate_ssh_context(context)
```

Importing the steps registers the step phrases, so `behave --dry-run` passes and
the gap stays invisible until the suite runs against a real VM.

Unit tests cannot catch this either: they stub `tests.shared.ssh_steps` wholesale
(see [unit-test-module-stubs](unit-test-module-stubs.md)), so the real
`run_ssh()` never executes. Assert on the suite's `before_all` instead — verify
it sets the attributes `run_ssh()` requires.

**Never keep a second, env-only SSH path alongside the shared steps.** A
suite-local helper that resolves `VM_IP`/`SSH_KEY` from `os.environ` itself will
keep working while the shared steps in the same suite fail, which masks the
missing wiring and creates two sources of truth. Resolve once, onto `context`,
and have suite-local helpers read the same resolved values.

Never duplicate `_ssh()` or generic step definitions in suite-specific `steps.py`.  
Default `run_ssh()` timeout: **60s** (not 30s — hardware commands are slow).
In `tests/common/features/`, `environment.py` already exports
`XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and `WAYLAND_DISPLAY` for every
SSH command via `ssh_command_prefix`. Prefer plain `systemctl --user`,
`gsettings`, and `gdbus` commands there instead of manually sourcing
`/tmp/session.env` inside each scenario.

For common-suite systemd health checks, oneshot services finish in `inactive (dead)`
after a successful run — their `ActiveState` is `inactive`, not `active`. Do NOT
assert `ActiveState==active` for units like `dconf-update.service`,
`ublue-system-setup.service`, `ublue-user-setup.service`, or
`bootc-unified-storage.service`. Use `Result` instead:

```gherkin
* Run SSH command: "systemctl show ublue-system-setup.service --property=Result --value"
* SSH command return code is "0"
* SSH command output stripped "is" "success"
```

The `Result` property is `success` when the service exited cleanly, `failed` if it
errored, and `exit-code` / `signal` for specific exit failures. Asserting
`ActiveState==active` on a completed oneshot always returns `inactive` and causes
false failures in QEMU CI even when the service ran correctly.

**Keep `@quarantine`** for services that are masked or disabled in the CI
`KERNEL_ARGS` (e.g. `flatpak-preinstall.service`) — those cannot be unquarantined
until the image-level masking is removed.

When a scenario is meant to fail on a bad command, never append `; true` (or
similar success-forcing trailers) to the SSH command. That masks the real exit
status and turns `SSH command return code is "0"` into a no-op. Use `2>&1` to
capture diagnostics, but preserve the original command's exit code.

## `ssh_argv()` owns the SSH argv for every suite

`tests/shared/ssh_config.ssh_argv(context, *, connect_timeout=10, quiet=False)` is the
single builder for SSH argv. Two properties of that contract are easy to get wrong:

- **`-p` is always emitted**, including when `SSH_PORT` is unset (it falls back to `22`).
  Do not write a test asserting the port flag is absent.
- **`quiet=True` adds `-o LogLevel=ERROR`, and it is opt-in per call site.** Only pass it
  where the old hand-rolled argv already suppressed the banner (`run_ssh`, `image_cache`,
  the software `_has_bazaar` probe, dx/flatcar/vanilla-gnome). Passing it everywhere hides
  diagnostics that kde-smoke and the screenshot helper rely on.
- **`connect_timeout` is per call site.** The default is 10s; a probe that previously used
  a longer connect window (e.g. the vanilla-gnome Flatpak probe, 20s) must pass
  `connect_timeout=` explicitly rather than relying on the command timeout.

Suites must not hand-roll `ssh` argv. `tests/unit/test_ssh_transport_contract.py`
enforces this for the modules listed in its `MIGRATED_MODULES` set — add new suites there
rather than copying an argv list.
