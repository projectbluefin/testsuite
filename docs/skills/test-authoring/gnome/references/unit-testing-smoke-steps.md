---
name: unit-testing-smoke-steps
description: "Unit-testing smoke step modules with stubbed dependencies."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Unit-testing smoke step modules

Smoke step modules drive AT-SPI, dogtail and live GNOME state, so most of their
surface is not unit-testable. What *is* testable is the pure logic they wrap:
command construction, output parsing, polling loops and assertion branches.
Import them in `tests/unit/` with `behave`, `qecore`, `dogtail` and
`app_support` stubbed via `sys.modules`, then patch the shell helper
(`_run_host`, `_run_in_vm`) with `unittest.mock.patch.object`.

Notes for the three a11y/input/XWayland modules:

- `orca_steps.py` — wraps `_run_host` from `steps.steps` (the smoke steps
  directory is only importable during a behave run, so unit tests must register
  a `steps` package stub with a `__path__` before importing). Unit-testable:
  the `Run command on VM` context bookkeeping, return-code/substring assertion
  messages, the `gsettings set …screen-reader-enabled` command string,
  `_orca_is_running()` (rc **and** non-empty stdout), `_wait_for_orca()` polling
  and its start/stop timeout wording, and the toggle step's guarantee that the
  screen-reader key is restored to `false` even when the start assertion fails.
  Not unit-testable: whether Orca actually starts.
- `input_methods_steps.py` — `_run_in_vm()` always prefixes
  `source /tmp/session.env 2>/dev/null;` and dispatches to `_ssh_run` when
  `_IN_CONTAINER`, else `subprocess.run(shell=True)`. `_restore_input_sources()`
  is idempotent via a `_restored` flag so the explicit restore step and the
  registered `context.add_cleanup` do not double-apply; the flag is latched only
  when every `gsettings set` returned 0, so a failed restore raises and the
  cleanup hook can retry instead of leaking state. Saved gsettings values
  contain single quotes and are re-applied through `shlex.quote`. Not
  unit-testable: whether IBus owns the bus name or a layout actually switches.
- `xwayland_steps.py` — `_xwayland_display_env()` parses `pgrep -a -x Xwayland`
  output: it takes the first line only, reads `-auth <file>` into `XAUTHORITY`
  (omitted when absent or dangling), and picks the first `:<digits>` token as
  `DISPLAY`, defaulting to `:0`. Not unit-testable: `xprop -root` against a real
  X root window, or glxgears rendering.
