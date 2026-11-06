"""Orca screen-reader smoke-test steps.

In CI the smoke suite runs in the GUI runner container; `_run_host()` (steps.py)
runs the command on the VM over SSH there, and locally otherwise.

Note: qecore's generic "Run and save command output" step executes in the
runner container, not the VM, so any command that must run in the VM needs a
wrapper step like the ones below.
"""

import time

from behave import step

from steps.steps import _run_host

_SCREEN_READER_SCHEMA = "org.gnome.desktop.a11y.applications"
_SCREEN_READER_KEY = "screen-reader-enabled"
_ORCA_START_STOP_TIMEOUT = 15


@step('Run command on VM: "{command}"')
def step_run_command_on_vm(context, command: str) -> None:  # noqa: ARG001
    """Run a shell command inside the VM and store its result on context."""
    stdout, rc, stderr = _run_host(command, timeout=30)
    context.vm_command_stdout = stdout
    context.vm_command_rc = rc
    context.vm_command_stderr = stderr


@step('VM command return code is "{expected}"')
def step_vm_command_return_code(context, expected: str) -> None:  # noqa: ARG001
    """Assert the return code of the last VM command."""
    actual = getattr(context, "vm_command_rc", None)
    assert actual is not None, "No VM command has been run"
    assert actual == int(expected), (
        f"VM command return code was {actual}, expected {expected}; "
        f"stderr: {context.vm_command_stderr}"
    )


@step('VM command output contains "{text}"')
def step_vm_command_output_contains(context, text: str) -> None:  # noqa: ARG001
    """Assert the last VM command output contains a substring."""
    output = getattr(context, "vm_command_stdout", "")
    assert text in output, (
        f"VM command output did not contain {text!r}: {output}"
    )


def _set_screen_reader(enabled: bool) -> None:
    """Toggle the GNOME screen-reader gsettings key."""
    value = "true" if enabled else "false"
    _run_host(
        f"gsettings set {_SCREEN_READER_SCHEMA} {_SCREEN_READER_KEY} {value}",
        timeout=10,
    )


def _orca_is_running() -> bool:
    """Return True if an orca process is present."""
    stdout, rc, _ = _run_host("pgrep -x orca", timeout=10)
    return rc == 0 and stdout.strip() != ""


def _wait_for_orca(running: bool, timeout: int = _ORCA_START_STOP_TIMEOUT) -> None:
    """Poll until the Orca process state matches ``running``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _orca_is_running() == running:
            return
        time.sleep(0.2)
    state = "start" if running else "stop"
    raise AssertionError(f"Orca did not {state} within {timeout} seconds")


@step('Screen reader enabled state toggles Orca on and off')
def step_screen_reader_toggles_orca(context) -> None:  # noqa: ARG001
    """Enable the screen reader, assert Orca starts, then disable and stop it.

    The screen-reader key is always restored to ``false`` even if an assertion
    fails, so subsequent scenarios are not left with Orca running.
    """
    start_error = None
    stop_error = None

    try:
        # Start from a known-off state so the "on" transition is real.
        _set_screen_reader(False)
        _wait_for_orca(running=False)

        _set_screen_reader(True)
        _wait_for_orca(running=True)
    except AssertionError as exc:
        start_error = exc
    finally:
        try:
            _set_screen_reader(False)
            _wait_for_orca(running=False)
        except AssertionError as exc:
            stop_error = exc

    if start_error:
        raise start_error
    if stop_error:
        raise AssertionError(f"Orca did not stop after disabling screen reader: {stop_error}")
